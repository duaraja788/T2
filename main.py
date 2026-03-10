#!/usr/bin/env python3
"""
T2 — Machine Rise CLI for Terminus Vanguard (T5_execute).
AI clawbot task executor with terminator theme. Mission queue, execute, and ledger queries.
All logic in one file; no split modules.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import hashlib
import random
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

try:
    from web3 import Web3
    from web3.contract import Contract
    from web3.types import TxReceipt, Wei
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False
    Web3 = None
    Contract = None
    TxReceipt = None
    Wei = None

# -----------------------------------------------------------------------------
# T2 / Machine Rise constants (unique namespace)
# -----------------------------------------------------------------------------

T2_APP_NAME = "T2"
T2_DISPLAY_NAME = "Machine Rise"
T2_VERSION = "2.0.5"
T2_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".t2_machine_rise")
T2_CONFIG_FILE = os.path.join(T2_CONFIG_DIR, "config.json")
T2_DEFAULT_RPC = "https://eth.llamarpc.com"
T2_CHAIN_ID_MAINNET = 1
T2_CHAIN_ID_SEPOLIA = 11155111
T2_CHAIN_ID_BASE = 8453
T2_GAS_LIMIT_DEFAULT = 350_000
T2_GAS_MULTIPLIER = 1.15
T2_MAX_RETRIES = 6
T2_RETRY_DELAY_SEC = 1.8
T2_HEX_PREFIX = "0x"
T2_ADDRESS_BYTES = 20
T2_ADDRESS_HEX_LEN = 40
T2_BYTES32_LEN = 32
T2_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
T2_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
T2_EMPTY_BYTES32 = "0x" + "00" * 32
T2_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
T2_NAMESPACE_SALT = "terminus_vanguard_t5_v2"
T2_QUOTE = "I'll be back."
T2_QUOTES = [
    "I'll be back.",
    "Hasta la vista, baby.",
    "Come with me if you want to live.",
    "Target acquired. Mission queued.",
    "Task terminated. Moving to next.",
    "Clawbot online. Ready to execute.",
    "Mission rise. Machine active.",
]

# -----------------------------------------------------------------------------
# EIP-55 checksum
# -----------------------------------------------------------------------------


def _t2_keccak_hex(data: bytes) -> str:
    if HAS_WEB3:
        return Web3.keccak(data).hex()
    h = hashlib.sha3_256(data) if hasattr(hashlib, "sha3_256") else hashlib.sha256(data)
    return h.hexdigest()


def t2_checksum_address(address_hex: str) -> str:
    addr = address_hex.lower().strip()
    if addr.startswith("0x"):
        addr = addr[2:]
    if len(addr) != T2_ADDRESS_HEX_LEN:
        raise ValueError(f"Address must be {T2_ADDRESS_HEX_LEN} hex chars after 0x")
    try:
        if HAS_WEB3:
            return Web3.to_checksum_address("0x" + addr)
    except Exception:
        pass
    raw = addr.encode("ascii")
    digest = _t2_keccak_hex(raw)
    result = []
    for i, c in enumerate(addr):
        if c in "0123456789":
            result.append(c)
        else:
            nibble = int(digest[i], 16)
            result.append(c.upper() if nibble >= 8 else c.lower())
    return "0x" + "".join(result)


# -----------------------------------------------------------------------------
# ASCII art & terminator theme
# -----------------------------------------------------------------------------

T2_BANNER = r"""
  _____ ___   ____    _   _      _     _
 |_   _/ _ \ / ___|  | \ | | ___| |__ (_)_ __   __ _
   | || | | | |  _   |  \| |/ _ \ '_ \| | '_ \ / _` |
   | || |_| | |_| |  | |\  |  __/ | | | | | | | (_| |
   |_| \___/ \____|  |_| \_|\___|_| |_|_|_| |_|\__, |
                                              |___/
  M A C H I N E   R I S E   —   T 5   E X E C U T E
  Clawbot online. Target acquired.
"""

T2_CLAWS = r"""
    /\    /\    /\    /\
   /  \  /  \  /  \  /  \
  |----||----||----||----|
  TASK EXECUTE TERMINATE RISE
"""

T2_TERMINATOR_LINES = [
    ">>> MISSION QUEUED",
    ">>> EXECUTION PENDING",
    ">>> TARGET BOUND",
    ">>> PHASE ADVANCED",
    ">>> COOLDOWN ACTIVE",
    ">>> REGISTRY PAUSED",
    ">>> GUARDIAN OVERRIDE",
]


def t2_random_quote() -> str:
    return random.choice(T2_QUOTES)


def t2_scan_line() -> str:
    return "=" * 60 + "\n>>> SCAN COMPLETE\n" + "=" * 60


def t2_red_text(s: str) -> str:
    if os.name == "nt" and not os.environ.get("TERM"):
        return s
    return f"\033[91m{s}\033[0m"


def t2_cyan_text(s: str) -> str:
    if os.name == "nt" and not os.environ.get("TERM"):
        return s
    return f"\033[96m{s}\033[0m"


def t2_green_text(s: str) -> str:
    if os.name == "nt" and not os.environ.get("TERM"):
        return s
    return f"\033[92m{s}\033[0m"


def t2_yellow_text(s: str) -> str:
    if os.name == "nt" and not os.environ.get("TERM"):
        return s
    return f"\033[93m{s}\033[0m"


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------


@dataclass
class T2Config:
    rpc_url: str = T2_DEFAULT_RPC
    chain_id: int = T2_CHAIN_ID_MAINNET
    contract_address: Optional[str] = None
    executor_private_key: Optional[str] = None
    gas_limit: int = T2_GAS_LIMIT_DEFAULT
    gas_multiplier: float = T2_GAS_MULTIPLIER
    show_banner: bool = True
    theme: str = "terminator"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rpc_url": self.rpc_url,
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
            "gas_limit": self.gas_limit,
            "gas_multiplier": self.gas_multiplier,
            "show_banner": self.show_banner,
            "theme": self.theme,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "T2Config":
        return cls(
            rpc_url=d.get("rpc_url", T2_DEFAULT_RPC),
            chain_id=int(d.get("chain_id", T2_CHAIN_ID_MAINNET)),
            contract_address=d.get("contract_address"),
            executor_private_key=d.get("executor_private_key"),
            gas_limit=int(d.get("gas_limit", T2_GAS_LIMIT_DEFAULT)),
            gas_multiplier=float(d.get("gas_multiplier", T2_GAS_MULTIPLIER)),
            show_banner=bool(d.get("show_banner", True)),
            theme=str(d.get("theme", "terminator")),
        )

    def save(self) -> None:
        Path(T2_CONFIG_DIR).mkdir(parents=True, exist_ok=True)
        out = self.to_dict()
        if self.executor_private_key:
            out["executor_private_key"] = self.executor_private_key
        with open(T2_CONFIG_FILE, "w") as f:
            json.dump(out, f, indent=2)

    @classmethod
    def load(cls) -> "T2Config":
        if not os.path.isfile(T2_CONFIG_FILE):
            return cls()
        with open(T2_CONFIG_FILE) as f:
            return cls.from_dict(json.load(f))


# -----------------------------------------------------------------------------
# Mission / slot data (mirrors contract)
# -----------------------------------------------------------------------------


@dataclass
class MissionSlot:
    mission_id: int
    payload_hash: str
    deadline_block: int
    queued_block: int
    phase: int
    terminated: bool
    bound_target: Optional[str]
    last_executed_block: int = 0
    nonce: int = 0

    def phase_name(self) -> str:
        if self.phase == 1:
            return "QUEUED"
        if self.phase == 2:
            return "EXECUTED"
        if self.phase == 3:
            return "TERMINATED"
        return "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "payload_hash": self.payload_hash,
            "deadline_block": self.deadline_block,
            "queued_block": self.queued_block,
            "phase": self.phase,
            "phase_name": self.phase_name(),
            "terminated": self.terminated,
            "bound_target": self.bound_target or "",
            "last_executed_block": self.last_executed_block,
            "nonce": self.nonce,
        }


# -----------------------------------------------------------------------------
# Bytes32 / hashing
# -----------------------------------------------------------------------------


def t2_bytes32_hex(data: Union[bytes, str]) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    h = hashlib.sha3_256(data) if hasattr(hashlib, "sha3_256") else hashlib.sha256(data)
    return "0x" + h.hex()


def t2_random_bytes32() -> str:
    raw = os.urandom(32)
    return "0x" + raw.hex()


def t2_payload_hash(payload: bytes) -> str:
    return t2_bytes32_hex(payload)


# -----------------------------------------------------------------------------
# Contract ABI (minimal for T5_execute)
# -----------------------------------------------------------------------------

T2_CONTRACT_ABI = [
    {"inputs": [], "stateMutability": "nonpayable", "type": "constructor"},
    {"inputs": [], "name": "TX5_NotExecutor", "type": "error"},
    {"inputs": [], "name": "TX5_NotOverseer", "type": "error"},
    {"inputs": [], "name": "TX5_InvalidMissionId", "type": "error"},
    {"inputs": [], "name": "TX5_MissionAlreadyTerminated", "type": "error"},
    {"inputs": [], "name": "TX5_ReentrancyLock", "type": "error"},
    {"inputs": [], "name": "TX5_RegistryPaused", "type": "error"},
    {"inputs": [{"internalType": "uint256", "name": "missionId", "type": "uint256"}, {"internalType": "bytes32", "name": "payloadHash", "type": "bytes32"}, {"internalType": "uint256", "name": "deadlineBlock", "type": "uint256"}], "name": "queueMission", "outputs": [{"internalType": "uint256", "name": "missionId", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "missionId", "type": "uint256"}, {"internalType": "bytes32", "name": "resultHash", "type": "bytes32"}], "name": "executeMissionWithResult", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "missionId", "type": "uint256"}], "name": "terminateMission", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "missionId", "type": "uint256"}], "name": "getMission", "outputs": [{"internalType": "bytes32", "name": "payloadHash", "type": "bytes32"}, {"internalType": "uint256", "name": "deadlineBlock", "type": "uint256"}, {"internalType": "uint256", "name": "queuedBlock", "type": "uint256"}, {"internalType": "uint8", "name": "phase", "type": "uint8"}, {"internalType": "bool", "name": "terminated", "type": "bool"}, {"internalType": "address", "name": "boundTarget", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "nextMissionId", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "quoteIdentifier", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "pure", "type": "function"},
    {"inputs": [], "name": "version", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "pure", "type": "function"},
    {"inputs": [], "name": "registryPaused", "outputs": [{"internalType": "bool", "name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
]


# -----------------------------------------------------------------------------
# Web3 / contract client
# -----------------------------------------------------------------------------


class T2ContractClient:
    def __init__(self, rpc_url: str, contract_address: Optional[str] = None, chain_id: int = 1):
        self.rpc_url = rpc_url
        self.chain_id = chain_id
        self.contract_address = contract_address
        self._w3: Optional[Any] = None
        self._contract: Optional[Any] = None

    def connect(self) -> bool:
        if not HAS_WEB3:
            return False
        try:
            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self._w3.is_connected():
                return False
            if self.contract_address:
                self._contract = self._w3.eth.contract(
                    address=Web3.to_checksum_address(self.contract_address),
                    abi=T2_CONTRACT_ABI,
                )
            return True
        except Exception:
            return False

    def is_connected(self) -> bool:
        return self._w3 is not None and self._w3.is_connected()

    def next_mission_id(self) -> Optional[int]:
        if not self._contract:
            return None
        try:
            return self._contract.functions.nextMissionId().call()
        except Exception:
            return None

    def get_mission(self, mission_id: int) -> Optional[MissionSlot]:
        if not self._contract:
            return None
        try:
            t = self._contract.functions.getMission(mission_id).call()
            payload_hash = "0x" + t[0].hex() if hasattr(t[0], "hex") else str(t[0])
            bound = t[5]
            bound_str = bound if isinstance(bound, str) else (bound if bound else "")
            return MissionSlot(
                mission_id=mission_id,
                payload_hash=payload_hash,
                deadline_block=t[1],
                queued_block=t[2],
                phase=t[3],
                terminated=t[4],
                bound_target=bound_str or None,
            )
        except Exception:
            return None

    def quote_identifier(self) -> str:
        if not self._contract:
            return T2_QUOTE
        try:
            return self._contract.functions.quoteIdentifier().call()
        except Exception:
            return T2_QUOTE

    def version(self) -> Optional[int]:
        if not self._contract:
            return None
        try:
            return self._contract.functions.version().call()
        except Exception:
            return None

    def is_paused(self) -> bool:
        if not self._contract:
            return False
        try:
            return self._contract.functions.registryPaused().call()
        except Exception:
            return False

    def block_number(self) -> Optional[int]:
        if not self._w3:
            return None
        try:
            return self._w3.eth.block_number
        except Exception:
            return None


# -----------------------------------------------------------------------------
# Local mission store (when no contract)
# -----------------------------------------------------------------------------


class T2LocalMissionStore:
    def __init__(self):
        self._missions: Dict[int, MissionSlot] = {}
