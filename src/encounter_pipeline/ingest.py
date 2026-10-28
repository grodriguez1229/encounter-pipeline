"""ingest: load 999 and 277CA files and match them to what we sent.

Matching is by control numbers, never by file name:
- a 999 names our GS06 (AK102) and ST02 (AK202), which identify one submission
- a 277CA names our BHT03 (TRN02 at the receiver level) to identify the submission,
  then CLM01 (TRN02 at the patient level) for each claim inside it

Anything that doesn't match goes to quarantine. Files already loaded are skipped.
"""

from datetime import datetime
from pathlib import Path

import duckdb

from encounter_pipeline.config import Config
from encounter_pipeline.x12.parser import parse
from encounter_pipeline.x12.read_277ca import File277CA, read_277ca
from encounter_pipeline.x12.read_999 import File999, read_999


def quarantine(con, file_name: str, reason: str, detail: str, received_at: datetime) -> None:
    con.execute("INSERT INTO quarantine VALUES (?, ?, ?, ?)",
                [file_name, reason, detail, received_at])


def load_999(con: duckdb.DuckDBPyConnection, file_name: str, f: File999) -> None:
    for ack in f.transactions:
        row = con.execute(
            "SELECT submission_id FROM submissions WHERE gs06 = ? AND st02 = ?",
            [ack.gs06, ack.st02],
        ).fetchone()
        if row is None:
            quarantine(con, file_name, "999: no submission with this GS06/ST02",
                       f"GS06={ack.gs06} ST02={ack.st02}", f.created)
            continue
        submission_id = row[0]
        con.execute(
            "INSERT INTO submission_acks VALUES (?, ?, ?, ?, ?, ?)",
            [submission_id, file_name, ack.accepted, ",".join(ack.codes) or None,
             "; ".join(ack.errors) or None, f.created],
        )
        if not ack.accepted:
            # The whole transaction set was rejected, so every claim in it was too.
            reason = ",".join(f"IK5:{c}" for c in ack.codes)
            con.execute("""
                INSERT INTO claim_status_history
                SELECT trip_id, submission_id, '999', 'rejected', ?, NULL, ?, ?
                FROM submission_claims WHERE submission_id = ?
            """, [reason, file_name, f.created, submission_id])


def load_277ca(con: duckdb.DuckDBPyConnection, file_name: str, f: File277CA) -> None:
    submission_id = int(f.batch_id) if f.batch_id.isdigit() else None
    known = {
        trip_id for (trip_id,) in con.execute(
            "SELECT trip_id FROM submission_claims WHERE submission_id = ?", [submission_id]
        ).fetchall()
    }
    if not known:
        quarantine(con, file_name, "277CA: no submission with this batch ID",
                   f"TRN02={f.batch_id}", f.created)
        return
    for claim in f.claims:
        if claim.trip_id not in known:
            quarantine(con, file_name, "277CA: claim not in that submission",
                       f"batch={f.batch_id} CLM01={claim.trip_id}", f.created)
            continue
        con.execute(
            "INSERT INTO claim_status_history VALUES (?, ?, '277CA', ?, ?, ?, ?, ?)",
            [claim.trip_id, submission_id, claim.status, ",".join(claim.status_codes),
             claim.payer_claim_number, file_name, f.created],
        )


def received_order(path: Path) -> tuple:
    """Load in the order the files arrived (ISA09/ISA10), so history reads in order."""
    isa = path.read_text().lstrip()[:106]
    fields = isa.split(isa[3])
    return (fields[9], fields[10], path.name)


def run(config: Config, con: duckdb.DuckDBPyConnection) -> None:
    loaded = {name for (name,) in con.execute("SELECT file_name FROM response_files").fetchall()}
    new_files = [p for p in config.inbound_dir.glob("*.x12") if p.name not in loaded]
    for path in sorted(new_files, key=received_order):
        text = path.read_text()
        # The file type comes from ST01, not the file name, which is the payer's choice.
        st01 = next(s[1] for s in parse(text) if s.id == "ST")
        con.begin()
        if st01 == "999":
            f = read_999(text)
            load_999(con, path.name, f)
            file_type = "999"
        elif st01 == "277":
            f = read_277ca(text)
            load_277ca(con, path.name, f)
            file_type = "277CA"
        else:
            raise ValueError(f"{path.name}: unexpected transaction set {st01}")
        con.execute("INSERT INTO response_files VALUES (?, ?, ?, ?, ?)",
                    [path.name, file_type, f.isa13, f.created, text])
        con.commit()
    print(f"ingest: loaded {len(new_files)} files")
