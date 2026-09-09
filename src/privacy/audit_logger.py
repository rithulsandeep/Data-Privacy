"""
Cryptographic Tamper-Evident Audit Logging for Healthcare Compliance.
Implements SHA-256 hash-chained immutable logging (HIPAA §164.312(b) & GDPR Art. 30):
- Every federated learning round, gradient exchange, privacy budget update, and access event is recorded.
- Each entry references the cryptographic digest of the prior entry, ensuring unalterable provenance.
"""

from typing import Dict, List, Optional, Any, Tuple
import hashlib
import json
import os
import time
from datetime import datetime


class AuditLogger:
    """Tamper-evident, hash-chained audit logger."""

    def __init__(self, log_file_path: Optional[str] = None):
        self.log_file_path = log_file_path
        self.chain: List[Dict[str, Any]] = []
        self.genesis_hash = "0" * 64
        self._init_genesis()

    def _init_genesis(self) -> None:
        """Initializes blockchain-style genesis block if chain is empty."""
        if not self.chain:
            genesis_entry = {
                "index": 0,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "actor_role": "system",
                "actor_id": "SYS_INIT",
                "action": "AUDIT_INITIALIZATION",
                "status": "SUCCESS",
                "details": {"message": "Cryptographic Audit Ledger Initialized for Healthcare FL System"},
                "prev_hash": self.genesis_hash
            }
            genesis_entry["entry_hash"] = self._compute_hash(genesis_entry)
            self.chain.append(genesis_entry)

    def _compute_hash(self, entry: Dict[str, Any]) -> str:
        """Computes SHA-256 digest of an entry."""
        payload = {
            "index": entry["index"],
            "timestamp": entry["timestamp"],
            "actor_role": entry["actor_role"],
            "actor_id": entry["actor_id"],
            "action": entry["action"],
            "status": entry["status"],
            "details": entry["details"],
            "prev_hash": entry["prev_hash"]
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def log(
        self,
        actor_role: str,
        actor_id: str,
        action: str,
        status: str = "SUCCESS",
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Appends a new verified event block to the audit chain."""
        prev_entry = self.chain[-1]
        new_index = len(self.chain)

        entry = {
            "index": new_index,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "actor_role": actor_role,
            "actor_id": actor_id,
            "action": action,
            "status": status,
            "details": details or {},
            "prev_hash": prev_entry["entry_hash"]
        }
        entry["entry_hash"] = self._compute_hash(entry)
        self.chain.append(entry)

        if self.log_file_path:
            self.save_to_file(self.log_file_path)

        return entry

    def verify_integrity(self) -> Tuple[bool, Optional[int]]:
        """
        Validates cryptographic integrity of the entire audit chain.
        Returns:
            (is_valid, corrupted_index)
        """
        for i in range(1, len(self.chain)):
            curr = self.chain[i]
            prev = self.chain[i - 1]

            # Verify link to previous entry
            if curr["prev_hash"] != prev["entry_hash"]:
                return False, i

            # Verify hash computation of current entry
            expected_hash = self._compute_hash(curr)
            if curr["entry_hash"] != expected_hash:
                return False, i

        return True, None

    def get_entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Returns recent audit entries."""
        return self.chain[-limit:]

    def save_to_file(self, file_path: str) -> None:
        """Persists audit log to disk."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.chain, f, indent=2)


# Global singleton instance for easy orchestration
audit_ledger = AuditLogger()
