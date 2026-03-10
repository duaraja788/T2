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
        self._next_id = 0
        self._current_block = 1000

    def next_mission_id(self) -> int:
        return self._next_id

    def queue(self, payload_hash: str, deadline_block: int) -> int:
        mid = self._next_id
        self._next_id += 1
        self._missions[mid] = MissionSlot(
            mission_id=mid,
            payload_hash=payload_hash,
            deadline_block=deadline_block,
            queued_block=self._current_block,
            phase=1,
            terminated=False,
            bound_target=None,
        )
        return mid

    def execute(self, mission_id: int, result_hash: str) -> bool:
        if mission_id not in self._missions:
            return False
        m = self._missions[mission_id]
        if m.terminated or m.phase != 1:
            return False
        m.phase = 2
        m.last_executed_block = self._current_block
        return True

    def terminate(self, mission_id: int) -> bool:
        if mission_id not in self._missions:
            return False
        self._missions[mission_id].terminated = True
        self._missions[mission_id].phase = 3
        return True

    def get_mission(self, mission_id: int) -> Optional[MissionSlot]:
        return self._missions.get(mission_id)

    def set_block(self, block: int) -> None:
        self._current_block = block

    def list_ids(self) -> List[int]:
        return sorted(self._missions.keys())


# -----------------------------------------------------------------------------
# CLI commands
# -----------------------------------------------------------------------------


def cmd_status(config: T2Config, client: Optional[T2ContractClient], local: T2LocalMissionStore) -> int:
    print(t2_cyan_text(T2_BANNER) if config.show_banner else "")
    print(t2_yellow_text(f"  {t2_random_quote()}"))
    print()
    if client and client.is_connected():
        nid = client.next_mission_id()
        print(t2_green_text(f"  Connected to chain_id={client.chain_id}"))
        if client.contract_address:
            print(t2_green_text(f"  Contract: {client.contract_address}"))
        if nid is not None:
            print(t2_green_text(f"  Next mission ID: {nid}"))
        print(t2_green_text(f"  Quote: {client.quote_identifier()}"))
        if client.version() is not None:
            print(t2_green_text(f"  Contract version: {client.version()}"))
        print(t2_green_text(f"  Paused: {client.is_paused()}"))
    else:
        print(t2_yellow_text("  No RPC/contract connected. Using local store."))
        print(t2_yellow_text(f"  Local next mission ID: {local.next_mission_id()}"))
        print(t2_yellow_text(f"  Local missions: {len(local.list_ids())}"))
    print(t2_scan_line())
    return 0


def cmd_queue(config: T2Config, client: Optional[T2ContractClient], local: T2LocalMissionStore, payload: str, deadline_blocks: int) -> int:
    payload_hash = t2_bytes32_hex(payload.encode("utf-8"))
    if client and client.is_connected() and client.contract_address:
        print(t2_red_text("  On-chain queue not implemented in this stub (no private key). Use local."))
    current_block = local._current_block if hasattr(local, "_current_block") else 1000
    deadline_block = current_block + deadline_blocks
    mid = local.queue(payload_hash, deadline_block)
    print(t2_green_text(f"  Mission queued. mission_id={mid}"))
    print(t2_green_text(f"  payload_hash={payload_hash}"))
    print(t2_green_text(f"  deadline_block={deadline_block}"))
    print(t2_yellow_text(f"  >>> {t2_random_quote()}"))
    return 0


def cmd_execute(config: T2Config, client: Optional[T2ContractClient], local: T2LocalMissionStore, mission_id: int, result_hash: Optional[str]) -> int:
    rh = result_hash or t2_random_bytes32()
    if local.execute(mission_id, rh):
        print(t2_green_text(f"  Mission {mission_id} executed. result_hash={rh}"))
        print(t2_yellow_text(f"  >>> {t2_random_quote()}"))
        return 0
    print(t2_red_text(f"  Mission {mission_id} not found or not executable."))
    return 1


def cmd_terminate(config: T2Config, client: Optional[T2ContractClient], local: T2LocalMissionStore, mission_id: int) -> int:
    if local.terminate(mission_id):
        print(t2_green_text(f"  Mission {mission_id} terminated."))
        print(t2_yellow_text(f"  >>> {t2_random_quote()}"))
        return 0
    print(t2_red_text(f"  Mission {mission_id} not found."))
    return 1


def cmd_get_mission(config: T2Config, client: Optional[T2ContractClient], local: T2LocalMissionStore, mission_id: int) -> int:
    m = client.get_mission(mission_id) if client and client.contract_address else local.get_mission(mission_id)
    if not m:
        print(t2_red_text(f"  Mission {mission_id} not found."))
        return 1
    print(json.dumps(m.to_dict(), indent=2))
    return 0


def cmd_list(config: T2Config, client: Optional[T2ContractClient], local: T2LocalMissionStore, limit: int) -> int:
    if client and client.is_connected() and client.contract_address:
        nid = client.next_mission_id()
        if nid is not None:
            print(t2_cyan_text(f"  Contract next mission ID: {nid}"))
            for i in range(min(nid, limit)):
                m = client.get_mission(i)
                if m:
                    print(json.dumps(m.to_dict(), indent=2))
                    print("  ---")
        return 0
    ids = local.list_ids()[:limit]
    for mid in ids:
        m = local.get_mission(mid)
        if m:
            print(json.dumps(m.to_dict(), indent=2))
            print("  ---")
    return 0


def cmd_quote(config: T2Config) -> int:
    print(t2_cyan_text(f"  {t2_random_quote()}"))
    return 0


def cmd_config_show(config: T2Config) -> int:
    d = config.to_dict()
    d.pop("executor_private_key", None)
    print(json.dumps(d, indent=2))
    return 0


def cmd_config_set(args: argparse.Namespace, config: T2Config) -> int:
    if getattr(args, "rpc_url", None):
        config.rpc_url = args.rpc_url
    if getattr(args, "chain_id", None) is not None:
        config.chain_id = int(args.chain_id)
    if getattr(args, "contract_address", None) is not None:
        config.contract_address = args.contract_address or None
    if getattr(args, "gas_limit", None) is not None:
        config.gas_limit = int(args.gas_limit)
    config.save()
    print(t2_green_text("  Config saved."))
    return 0


# -----------------------------------------------------------------------------
# Animation (terminator-style scan)
# -----------------------------------------------------------------------------


def run_scan_animation(duration_sec: float = 1.5) -> None:
    end = time.monotonic() + duration_sec
    i = 0
    chars = ["/", "-", "\\", "|"]
    while time.monotonic() < end:
        sys.stdout.write(f"\r  >>> SCANNING {chars[i % 4]} ")
        sys.stdout.flush()
        time.sleep(0.08)
        i += 1
    sys.stdout.write("\r  >>> SCAN COMPLETE.        \n")
    sys.stdout.flush()


# -----------------------------------------------------------------------------
# Validation and encoding helpers
# -----------------------------------------------------------------------------


def t2_validate_mission_id(mission_id: int) -> bool:
    return 0 <= mission_id < 88_888


def t2_validate_address(addr: str) -> bool:
    if not addr or not addr.startswith("0x"):
        return False
    rest = addr[2:].lower()
    if len(rest) != 40:
        return False
    return all(c in "0123456789abcdef" for c in rest)


def t2_validate_bytes32(hex_str: str) -> bool:
    if not hex_str.startswith("0x"):
        return False
    rest = hex_str[2:].lower()
    return len(rest) == 64 and all(c in "0123456789abcdef" for c in rest)


def t2_encode_mission_params(mission_id: int, payload_hash: str, deadline_block: int) -> Dict[str, Any]:
    return {
        "mission_id": mission_id,
        "payload_hash": payload_hash,
        "deadline_block": deadline_block,
    }


def t2_decode_mission_from_dict(d: Dict[str, Any]) -> Optional[MissionSlot]:
    try:
        mid = int(d["mission_id"])
        ph = str(d.get("payload_hash", T2_EMPTY_BYTES32))
        dl = int(d["deadline_block"])
        qb = int(d.get("queued_block", 0))
        phase = int(d.get("phase", 1))
        term = bool(d.get("terminated", False))
        bound = d.get("bound_target") or None
        last_exec = int(d.get("last_executed_block", 0))
        nonce = int(d.get("nonce", 0))
        return MissionSlot(
            mission_id=mid,
            payload_hash=ph,
            deadline_block=dl,
            queued_block=qb,
            phase=phase,
            terminated=term,
            bound_target=bound,
            last_executed_block=last_exec,
            nonce=nonce,
        )
    except (KeyError, TypeError, ValueError):
        return None


# -----------------------------------------------------------------------------
# Batch and export helpers
# -----------------------------------------------------------------------------


def t2_export_missions_to_json(missions: List[MissionSlot]) -> str:
    return json.dumps([m.to_dict() for m in missions], indent=2)


def t2_import_missions_from_json(json_str: str) -> List[MissionSlot]:
    data = json.loads(json_str)
    out = []
    for item in data if isinstance(data, list) else [data]:
        m = t2_decode_mission_from_dict(item)
        if m:
            out.append(m)
    return out


def t2_mission_summary_table(missions: List[MissionSlot]) -> List[str]:
    lines = []
    lines.append("  mission_id | phase     | terminated | deadline_block | payload_hash (first 18)")
    lines.append("  " + "-" * 90)
    for m in missions:
        ph_short = (m.payload_hash[:20] + "..") if len(m.payload_hash) > 20 else m.payload_hash
        lines.append(f"  {m.mission_id:10} | {m.phase_name():10} | {str(m.terminated):10} | {m.deadline_block:14} | {ph_short}")
    return lines


def t2_filter_by_phase(missions: List[MissionSlot], phase: int) -> List[MissionSlot]:
    return [m for m in missions if m.phase == phase]


def t2_filter_by_terminated(missions: List[MissionSlot], terminated: bool) -> List[MissionSlot]:
    return [m for m in missions if m.terminated == terminated]


def t2_filter_executable(missions: List[MissionSlot], current_block: int, cooldown_blocks: int = 12) -> List[MissionSlot]:
    out = []
    for m in missions:
        if m.terminated or m.phase != 1:
            continue
        if current_block > m.deadline_block:
            continue
        if m.last_executed_block and current_block < m.last_executed_block + cooldown_blocks:
            continue
        out.append(m)
    return out


# -----------------------------------------------------------------------------
# More theme / display
# -----------------------------------------------------------------------------


T2_PHASE_BANNERS = {
    1: ">>> PHASE: QUEUED — AWAITING EXECUTION",
    2: ">>> PHASE: EXECUTED — MISSION COMPLETE",
    3: ">>> PHASE: TERMINATED — HASTA LA VISTA",
}


def t2_phase_banner(phase: int) -> str:
    return T2_PHASE_BANNERS.get(phase, ">>> PHASE: UNKNOWN")


def t2_display_mission(m: MissionSlot, use_color: bool = True) -> str:
    lines = [
        f"  Mission ID: {m.mission_id}",
        f"  Payload Hash: {m.payload_hash}",
        f"  Deadline Block: {m.deadline_block}",
        f"  Queued Block: {m.queued_block}",
        f"  Phase: {m.phase_name()} ({m.phase})",
        f"  Terminated: {m.terminated}",
        f"  Bound Target: {m.bound_target or '(none)'}",
        f"  Last Executed Block: {m.last_executed_block}",
        f"  Nonce: {m.nonce}",
    ]
    text = "\n".join(lines)
    if use_color:
        return t2_cyan_text(text)
    return text


def t2_ticker_line() -> str:
    return "  " + " * ".join(T2_TERMINATOR_LINES[:4]) + " "


# -----------------------------------------------------------------------------
# Additional CLI commands
# -----------------------------------------------------------------------------


def cmd_summary(config: T2Config, client: Optional[T2ContractClient], local: T2LocalMissionStore) -> int:
    ids = local.list_ids()
    missions = [local.get_mission(mid) for mid in ids]
    missions = [m for m in missions if m is not None]
    if not missions:
        print(t2_yellow_text("  No missions in local store."))
        return 0
    for line in t2_mission_summary_table(missions):
        print(line)
    print(t2_yellow_text(f"  >>> {t2_random_quote()}"))
    return 0


def cmd_export(config: T2Config, local: T2LocalMissionStore, path: str) -> int:
    ids = local.list_ids()
    missions = [local.get_mission(mid) for mid in ids]
    missions = [m for m in missions if m is not None]
    js = t2_export_missions_to_json(missions)
    with open(path, "w") as f:
        f.write(js)
    print(t2_green_text(f"  Exported {len(missions)} missions to {path}"))
    return 0


def cmd_import(config: T2Config, local: T2LocalMissionStore, path: str) -> int:
    with open(path) as f:
        missions = t2_import_missions_from_json(f.read())
    existing = set(local.list_ids())
    count = 0
    for m in missions:
        if m.mission_id not in existing:
            local._missions[m.mission_id] = m
            if local._next_id <= m.mission_id:
                local._next_id = m.mission_id + 1
            count += 1
    print(t2_green_text(f"  Imported {count} missions from {path}"))
    return 0


def cmd_executable(config: T2Config, local: T2LocalMissionStore, current_block: Optional[int], cooldown: int) -> int:
    cb = current_block or local._current_block
    ids = local.list_ids()
    missions = [local.get_mission(mid) for mid in ids]
    missions = [m for m in missions if m is not None]
    executable = t2_filter_executable(missions, cb, cooldown)
    print(t2_cyan_text(f"  Current block (sim): {cb}  Cooldown: {cooldown}"))
    print(t2_green_text(f"  Executable missions: {len(executable)}"))
    for m in executable:
        print(f"    mission_id={m.mission_id}  deadline_block={m.deadline_block}")
    return 0


def cmd_version(config: T2Config) -> int:
    print(t2_cyan_text(f"  {T2_APP_NAME} ({T2_DISPLAY_NAME}) version {T2_VERSION}"))
    print(t2_yellow_text(f"  {t2_random_quote()}"))
    return 0


def cmd_banner(config: T2Config) -> int:
    print(t2_cyan_text(T2_BANNER))
    print(t2_red_text(T2_CLAWS))
    print(t2_yellow_text(t2_ticker_line()))
    return 0


def cmd_validate_address(config: T2Config, address: str) -> int:
    ok = t2_validate_address(address)
    if ok:
        try:
            cs = t2_checksum_address(address)
            print(t2_green_text(f"  Valid. Checksum: {cs}"))
        except Exception as e:
            print(t2_red_text(f"  Invalid: {e}"))
    else:
        print(t2_red_text("  Invalid address format."))
    return 0 if ok else 1


def cmd_hash_payload(config: T2Config, payload: str) -> int:
    h = t2_bytes32_hex(payload.encode("utf-8"))
    print(t2_green_text(f"  payload_hash: {h}"))
    return 0


def cmd_random_bytes32(config: T2Config) -> int:
    print(t2_green_text(f"  {t2_random_bytes32()}"))
    return 0


# -----------------------------------------------------------------------------
# Contract client extended methods (read-only)
# -----------------------------------------------------------------------------


def t2_client_get_config(client: T2ContractClient) -> Optional[Dict[str, Any]]:
    if not client or not client._contract:
        return None
    try:
        max_m = client._contract.functions.maxMissions().call()
        cooldown = client._contract.functions.cooldownBlocks().call()
        cap = client._contract.functions.withdrawCapWei().call()
        ver = client._contract.functions.version().call()
        return {"max_missions": max_m, "cooldown_blocks": cooldown, "withdraw_cap_wei": cap, "version": ver}
    except Exception:
        return None


def cmd_contract_config(config: T2Config, client: Optional[T2ContractClient]) -> int:
    if not client or not client.is_connected():
        print(t2_red_text("  Not connected to contract."))
        return 1
    cfg = t2_client_get_config(client)
    if not cfg:
        print(t2_red_text("  Could not read contract config."))
        return 1
    print(json.dumps(cfg, indent=2))
    return 0


# -----------------------------------------------------------------------------
# Simulated block advance (local store)
# -----------------------------------------------------------------------------


def cmd_advance_block(config: T2Config, local: T2LocalMissionStore, blocks: int) -> int:
    local._current_block += blocks
    print(t2_green_text(f"  Block advanced by {blocks}. Current block: {local._current_block}"))
    return 0


# -----------------------------------------------------------------------------
# More ABI entries (view only) for reference
# -----------------------------------------------------------------------------

T2_VIEW_SELECTORS = [
    "nextMissionId()",
    "getMission(uint256)",
    "quoteIdentifier()",
    "version()",
    "registryPaused()",
    "maxMissions()",
    "cooldownBlocks()",
    "withdrawCapWei()",
    "getConfig()",
    "missionSummary(uint256)",
    "isMissionExecutable(uint256)",
    "blocksUntilDeadline(uint256)",
    "checkCooldown(uint256)",
]


def cmd_abi_selectors(config: T2Config) -> int:
    for sel in T2_VIEW_SELECTORS:
        print(f"  {sel}")
    return 0


# -----------------------------------------------------------------------------
# Mission lifecycle simulation (local only)
# -----------------------------------------------------------------------------


def t2_simulate_mission_lifecycle(
    store: T2LocalMissionStore,
    payload: str,
    deadline_offset: int,
    result_hash: Optional[str] = None,
) -> Tuple[bool, str]:
    """Queue a mission, advance block, execute, return (success, message)."""
    ph = t2_bytes32_hex(payload.encode("utf-8"))
    current = store._current_block
    deadline = current + deadline_offset
    mid = store.queue(ph, deadline)
    store._current_block += 1
    rh = result_hash or t2_random_bytes32()
    ok = store.execute(mid, rh)
    if ok:
        return True, f"Mission {mid} queued and executed."
    return False, f"Mission {mid} queued but execution failed."


def cmd_simulate(config: T2Config, local: T2LocalMissionStore, payload: str, offset: int) -> int:
    ok, msg = t2_simulate_mission_lifecycle(local, payload, offset)
    if ok:
        print(t2_green_text(f"  {msg}"))
    else:
        print(t2_red_text(f"  {msg}"))
    return 0 if ok else 1


# -----------------------------------------------------------------------------
# Chain ID helpers
# -----------------------------------------------------------------------------

T2_CHAIN_NAMES = {
    1: "mainnet",
    11155111: "sepolia",
    8453: "base",
    137: "polygon",
    42161: "arbitrum_one",
    10: "optimism",
}


def t2_chain_name(chain_id: int) -> str:
    return T2_CHAIN_NAMES.get(chain_id, f"chain_{chain_id}")


def cmd_chain_info(config: T2Config) -> int:
    print(t2_cyan_text(f"  chain_id: {config.chain_id}  name: {t2_chain_name(config.chain_id)}"))
    return 0


# -----------------------------------------------------------------------------
# Logging stub (no external logger)
# -----------------------------------------------------------------------------


def t2_log(level: str, message: str) -> None:
    ts = time.strftime(T2_DATE_FORMAT, time.localtime())
    print(f"{ts} [{level}] T2: {message}")


def t2_log_debug(msg: str) -> None:
    t2_log("DEBUG", msg)


def t2_log_info(msg: str) -> None:
    t2_log("INFO", msg)


def t2_log_warning(msg: str) -> None:
    t2_log("WARNING", msg)


def t2_log_error(msg: str) -> None:
    t2_log("ERROR", msg)


# -----------------------------------------------------------------------------
# Retry logic for RPC (generic)
# -----------------------------------------------------------------------------


def t2_retry_rpc(func: Callable[[], Any], max_retries: int = T2_MAX_RETRIES, delay: float = T2_RETRY_DELAY_SEC) -> Any:
    last_err = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(delay)
    raise last_err


# -----------------------------------------------------------------------------
# Hex and number formatting
# -----------------------------------------------------------------------------


def t2_hex_to_int(hex_str: str) -> int:
    if hex_str.startswith("0x"):
        hex_str = hex_str[2:]
    return int(hex_str, 16)


def t2_int_to_hex(n: int, pad_bytes: int = 32) -> str:
    w = pad_bytes * 2
    h = hex(n)[2:].lower()
    if len(h) > w:
        return "0x" + h[-w:]
    return "0x" + h.zfill(w)


def t2_shorten_hash(h: str, prefix: int = 8, suffix: int = 6) -> str:
    if len(h) <= prefix + suffix + 2:
        return h
    return h[: 2 + prefix] + "..." + h[-suffix:]


# -----------------------------------------------------------------------------
# Default payloads for demos
# -----------------------------------------------------------------------------

T2_DEMO_PAYLOADS = [
    "terminate_target_alpha",
    "acquire_resource_beta",
    "execute_phase_gamma",
    "clawbot_mission_rise",
    "machine_vanguard_task",
]


def t2_random_demo_payload() -> str:
    return random.choice(T2_DEMO_PAYLOADS)


def cmd_queue_demo(config: T2Config, local: T2LocalMissionStore, count: int, deadline_blocks: int) -> int:
    for _ in range(count):
        payload = t2_random_demo_payload()
        ph = t2_bytes32_hex(payload.encode("utf-8"))
        current = local._current_block
        mid = local.queue(ph, current + deadline_blocks)
        print(t2_green_text(f"  Queued mission_id={mid}  payload={payload}"))
    print(t2_yellow_text(f"  >>> {t2_random_quote()}"))
    return 0


# -----------------------------------------------------------------------------
# Contract address validation (EIP-55)
# -----------------------------------------------------------------------------


def t2_normalize_contract_address(addr: Optional[str]) -> Optional[str]:
    if not addr:
        return None
    addr = addr.strip()
    if not addr.startswith("0x"):
        addr = "0x" + addr
    if len(addr) != 42:
        return None
    try:
        return t2_checksum_address(addr)
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Config validation
# -----------------------------------------------------------------------------


def t2_validate_config(config: T2Config) -> List[str]:
    errors = []
    if not config.rpc_url or not config.rpc_url.startswith("http"):
        errors.append("rpc_url must be a valid HTTP(S) URL")
    if config.chain_id < 1:
        errors.append("chain_id must be positive")
    if config.contract_address and not t2_validate_address(config.contract_address):
        errors.append("contract_address must be 0x + 40 hex chars")
    if config.gas_limit < 21000:
        errors.append("gas_limit must be >= 21000")
    return errors


def cmd_validate_config(config: T2Config) -> int:
    errs = t2_validate_config(config)
    if not errs:
        print(t2_green_text("  Config valid."))
        return 0
    for e in errs:
        print(t2_red_text(f"  {e}"))
    return 1


# -----------------------------------------------------------------------------
# Mission ID range helpers
# -----------------------------------------------------------------------------


def t2_mission_id_range(next_id: int, limit: int = 100) -> List[int]:
    if next_id == 0:
        return []
    end = min(next_id, limit)
    return list(range(0, end))


# -----------------------------------------------------------------------------
# Result hash from payload + nonce (mirror contract logic)
# -----------------------------------------------------------------------------


def t2_compute_result_hash(payload_hash: str, execution_digest: str) -> str:
    combined = payload_hash.encode("utf-8") if isinstance(payload_hash, str) else payload_hash
    combined += execution_digest.encode("utf-8") if isinstance(execution_digest, str) else execution_digest
    return t2_bytes32_hex(combined)


# -----------------------------------------------------------------------------
# Banner variants
# -----------------------------------------------------------------------------

T2_BANNER_MINIMAL = "  T2 | Machine Rise | T5_execute\n  Clawbot online.\n"


def t2_get_banner(minimal: bool = False) -> str:
    return T2_BANNER_MINIMAL if minimal else T2_BANNER


# -----------------------------------------------------------------------------
# Table formatting utilities
# -----------------------------------------------------------------------------


def t2_table_row(cells: List[str], widths: List[int], sep: str = " | ") -> str:
    padded = []
    for i, c in enumerate(cells):
        w = widths[i] if i < len(widths) else 12
        padded.append(c[:w].ljust(w) if len(c) <= w else c[: w - 3] + "...")
    return sep.join(padded)


def t2_table_header(headers: List[str], widths: Optional[List[int]] = None) -> str:
    w = widths or [14] * len(headers)
    return t2_table_row(headers, w)


def t2_table_separator(num_cols: int, width: int = 14) -> str:
    return "  " + "-" * (num_cols * (width + 3) - 3)


# -----------------------------------------------------------------------------
# Mission stats aggregation
# -----------------------------------------------------------------------------


def t2_mission_stats(missions: List[MissionSlot]) -> Dict[str, Any]:
    if not missions:
        return {"count": 0, "by_phase": {}, "terminated_count": 0}
    by_phase: Dict[int, int] = {}
    term_count = 0
    for m in missions:
        by_phase[m.phase] = by_phase.get(m.phase, 0) + 1
        if m.terminated:
            term_count += 1
    return {"count": len(missions), "by_phase": by_phase, "terminated_count": term_count}


def cmd_stats(config: T2Config, local: T2LocalMissionStore) -> int:
    ids = local.list_ids()
    missions = [local.get_mission(mid) for mid in ids]
    missions = [m for m in missions if m is not None]
    stats = t2_mission_stats(missions)
    print(json.dumps(stats, indent=2))
    return 0


# -----------------------------------------------------------------------------
# Environment and feature flags
# -----------------------------------------------------------------------------

T2_ENV_RPC = "T2_RPC_URL"
T2_ENV_CONTRACT = "T2_CONTRACT_ADDRESS"
T2_ENV_CHAIN_ID = "T2_CHAIN_ID"


def t2_config_from_env(config: T2Config) -> T2Config:
    if os.environ.get(T2_ENV_RPC):
        config.rpc_url = os.environ[T2_ENV_RPC]
    if os.environ.get(T2_ENV_CONTRACT):
        config.contract_address = os.environ[T2_ENV_CONTRACT]
    if os.environ.get(T2_ENV_CHAIN_ID):
        try:
            config.chain_id = int(os.environ[T2_ENV_CHAIN_ID])
        except ValueError:
            pass
    return config


def cmd_env_info(config: T2Config) -> int:
    print(t2_cyan_text("  Environment variables (T2):"))
    print(f"    {T2_ENV_RPC} = {os.environ.get(T2_ENV_RPC, '(not set)')}")
    print(f"    {T2_ENV_CONTRACT} = {os.environ.get(T2_ENV_CONTRACT, '(not set)')}")
    print(f"    {T2_ENV_CHAIN_ID} = {os.environ.get(T2_ENV_CHAIN_ID, '(not set)')}")
    return 0


# -----------------------------------------------------------------------------
# Help text for contract interaction
# -----------------------------------------------------------------------------

T2_HELP_CONTRACT = """
  T2 connects to T5_execute (Terminus Vanguard) contract.
  Set --contract and --rpc to query on-chain state.
  Commands: status, get, list, contract-config, quote (from contract when connected).
  Local-only: queue, execute, terminate, summary, export, import, advance-block, queue-demo, simulate.
"""


def cmd_help_contract(config: T2Config) -> int:
    print(t2_cyan_text(T2_HELP_CONTRACT))
    return 0


# -----------------------------------------------------------------------------
# Cooldown calculation (mirror contract)
# -----------------------------------------------------------------------------


def t2_cooldown_remaining(last_executed_block: int, current_block: int, cooldown_blocks: int = 12) -> int:
    if last_executed_block == 0:
        return 0
    end = last_executed_block + cooldown_blocks
    if current_block >= end:
        return 0
    return end - current_block


def t2_can_execute_now(
    mission: MissionSlot,
    current_block: int,
    cooldown_blocks: int = 12,
) -> bool:
    if mission.terminated or mission.phase != 1:
        return False
    if current_block > mission.deadline_block:
        return False
    if mission.last_executed_block == 0:
        return True
    return current_block >= mission.last_executed_block + cooldown_blocks


# -----------------------------------------------------------------------------
# Deadline countdown
# -----------------------------------------------------------------------------


def t2_blocks_until_deadline(mission: MissionSlot, current_block: int) -> int:
    if current_block >= mission.deadline_block:
        return 0
    return mission.deadline_block - current_block


# -----------------------------------------------------------------------------
# Colored phase output
# -----------------------------------------------------------------------------


def t2_phase_color(phase: int) -> Callable[[str], str]:
    if phase == 1:
        return t2_yellow_text
    if phase == 2:
        return t2_green_text
    if phase == 3:
        return t2_red_text
    return lambda s: s


# -----------------------------------------------------------------------------
# Single mission display (compact)
# -----------------------------------------------------------------------------


def t2_mission_line(m: MissionSlot) -> str:
    return f"  #{m.mission_id}  {m.phase_name():10}  terminated={m.terminated}  deadline={m.deadline_block}  payload={t2_shorten_hash(m.payload_hash)}"


# -----------------------------------------------------------------------------
# Gas estimation stubs (for future use)
# -----------------------------------------------------------------------------

T2_GAS_QUEUE_MISSION = 120_000
T2_GAS_EXECUTE_MISSION = 80_000
T2_GAS_TERMINATE_MISSION = 60_000
T2_GAS_BIND_TARGET = 70_000


def t2_estimate_gas_queue() -> int:
    return T2_GAS_QUEUE_MISSION


def t2_estimate_gas_execute() -> int:
    return T2_GAS_EXECUTE_MISSION


def cmd_gas_estimates(config: T2Config) -> int:
    print(t2_cyan_text("  Gas estimates (stub):"))
    print(f"    queueMission:     {t2_estimate_gas_queue()}")
    print(f"    executeMission:  {t2_estimate_gas_execute()}")
    print(f"    terminateMission: {T2_GAS_TERMINATE_MISSION}")
    print(f"    bindTarget:      {T2_GAS_BIND_TARGET}")
    return 0


# -----------------------------------------------------------------------------
# Bytes32 from string (reusable)
# -----------------------------------------------------------------------------


def t2_string_to_bytes32(s: str) -> str:
    return t2_bytes32_hex(s.encode("utf-8"))


def t2_bytes_to_bytes32(b: bytes) -> str:
    return t2_bytes32_hex(b)


# -----------------------------------------------------------------------------
# Mission ID generator (local sim)
# -----------------------------------------------------------------------------


def t2_next_local_mission_id(store: T2LocalMissionStore) -> int:
    return store.next_mission_id()


# -----------------------------------------------------------------------------
# Contract roles (for display)
# -----------------------------------------------------------------------------

T2_ROLES = ["executor", "overseer", "guardian"]


def t2_role_display_names() -> List[str]:
    return list(T2_ROLES)


# -----------------------------------------------------------------------------
# Error messages (aligned with contract errors)
# -----------------------------------------------------------------------------

T2_ERR_NOT_EXECUTOR = "TX5_NotExecutor"
T2_ERR_NOT_OVERSEER = "TX5_NotOverseer"
T2_ERR_INVALID_MISSION_ID = "TX5_InvalidMissionId"
T2_ERR_MISSION_ALREADY_TERMINATED = "TX5_MissionAlreadyTerminated"
T2_ERR_REENTRANCY = "TX5_ReentrancyLock"
T2_ERR_PAUSED = "TX5_RegistryPaused"


def t2_error_message(err_code: str) -> str:
    return err_code.replace("TX5_", "Contract error: ")


# -----------------------------------------------------------------------------
# Version info dict
# -----------------------------------------------------------------------------


def t2_version_info() -> Dict[str, Any]:
    return {
        "app": T2_APP_NAME,
        "display_name": T2_DISPLAY_NAME,
        "version": T2_VERSION,
        "quote": T2_QUOTE,
        "has_web3": HAS_WEB3,
    }


def cmd_version_full(config: T2Config) -> int:
    print(json.dumps(t2_version_info(), indent=2))
    return 0


# -----------------------------------------------------------------------------
# Default deadline offset (blocks)
# -----------------------------------------------------------------------------

T2_DEFAULT_DEADLINE_OFFSET = 100


def t2_default_deadline_blocks() -> int:
    return T2_DEFAULT_DEADLINE_OFFSET


def t2_cooldown_blocks_default() -> int:
    return 12


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{T2_APP_NAME} — {T2_DISPLAY_NAME} CLI for T5_execute")
    parser.add_argument("--no-banner", action="store_true", help="Skip banner")
    parser.add_argument("--rpc", default=None, help="RPC URL")
    parser.add_argument("--contract", default=None, help="Contract address")
    sub = parser.add_subparsers(dest="command", help="Commands")

    p_status = sub.add_parser("status", help="Show status and quote")
    p_status.set_defaults(func=lambda a, c, cl, loc: cmd_status(c, cl, loc))

    p_queue = sub.add_parser("queue", help="Queue a mission (local)")
    p_queue.add_argument("payload", nargs="?", default="default_payload", help="Payload string")
    p_queue.add_argument("--deadline-blocks", type=int, default=100, help="Blocks until deadline")
    p_queue.set_defaults(func=lambda a, c, cl, loc: cmd_queue(c, cl, loc, a.payload, a.deadline_blocks))

    p_exec = sub.add_parser("execute", help="Execute mission (local)")
    p_exec.add_argument("mission_id", type=int, help="Mission ID")
    p_exec.add_argument("--result-hash", default=None, help="Result hash (optional)")
    p_exec.set_defaults(func=lambda a, c, cl, loc: cmd_execute(c, cl, loc, a.mission_id, a.result_hash))

    p_term = sub.add_parser("terminate", help="Terminate mission (local)")
    p_term.add_argument("mission_id", type=int, help="Mission ID")
    p_term.set_defaults(func=lambda a, c, cl, loc: cmd_terminate(c, cl, loc, a.mission_id))

    p_get = sub.add_parser("get", help="Get mission by ID")
    p_get.add_argument("mission_id", type=int, help="Mission ID")
    p_get.set_defaults(func=lambda a, c, cl, loc: cmd_get_mission(c, cl, loc, a.mission_id))

    p_list = sub.add_parser("list", help="List missions")
    p_list.add_argument("--limit", type=int, default=20, help="Max to show")
    p_list.set_defaults(func=lambda a, c, cl, loc: cmd_list(c, cl, loc, a.limit))

    p_quote = sub.add_parser("quote", help="Print random quote")
    p_quote.set_defaults(func=lambda a, c, cl, loc: cmd_quote(c))

    p_cfg = sub.add_parser("config", help="Show config")
    p_cfg.set_defaults(func=lambda a, c, cl, loc: cmd_config_show(c))

    p_cfg_set = sub.add_parser("config-set", help="Set config")
    p_cfg_set.add_argument("--rpc-url", default=None)
    p_cfg_set.add_argument("--chain-id", default=None)
    p_cfg_set.add_argument("--contract-address", default=None)
    p_cfg_set.add_argument("--gas-limit", default=None)
    p_cfg_set.set_defaults(func=lambda a, c, cl, loc: cmd_config_set(a, c))

    p_scan = sub.add_parser("scan", help="Run scan animation")
    p_scan.add_argument("--duration", type=float, default=1.5, help="Seconds")
    p_scan.set_defaults(func=lambda a, c, cl, loc: (run_scan_animation(a.duration), 0)[1])

    p_summary = sub.add_parser("summary", help="Table summary of local missions")
    p_summary.set_defaults(func=lambda a, c, cl, loc: cmd_summary(c, cl, loc))

    p_export = sub.add_parser("export", help="Export missions to JSON file")
    p_export.add_argument("path", help="Output file path")
    p_export.set_defaults(func=lambda a, c, cl, loc: cmd_export(c, loc, a.path))

    p_import = sub.add_parser("import", help="Import missions from JSON file")
    p_import.add_argument("path", help="Input file path")
    p_import.set_defaults(func=lambda a, c, cl, loc: cmd_import(c, loc, a.path))

    p_executable = sub.add_parser("executable", help="List executable missions (local)")
    p_executable.add_argument("--block", type=int, default=None, help="Current block (default: local sim)")
    p_executable.add_argument("--cooldown", type=int, default=12, help="Cooldown blocks")
    p_executable.set_defaults(func=lambda a, c, cl, loc: cmd_executable(c, loc, a.block, a.cooldown))

    p_version = sub.add_parser("version", help="Show app version and quote")
    p_version.set_defaults(func=lambda a, c, cl, loc: cmd_version(c))

    p_banner = sub.add_parser("banner", help="Print full banner and claws")
    p_banner.set_defaults(func=lambda a, c, cl, loc: cmd_banner(c))

    p_validate_addr = sub.add_parser("validate-address", help="Validate EIP-55 address")
    p_validate_addr.add_argument("address", help="Address to validate")
    p_validate_addr.set_defaults(func=lambda a, c, cl, loc: cmd_validate_address(c, a.address))

    p_hash = sub.add_parser("hash-payload", help="Hash payload string to bytes32")
    p_hash.add_argument("payload", nargs="?", default="default", help="Payload string")
    p_hash.set_defaults(func=lambda a, c, cl, loc: cmd_hash_payload(c, a.payload))

    p_rand32 = sub.add_parser("random-bytes32", help="Generate random bytes32 hex")
    p_rand32.set_defaults(func=lambda a, c, cl, loc: cmd_random_bytes32(c))

    p_contract_cfg = sub.add_parser("contract-config", help="Print contract config (when connected)")
    p_contract_cfg.set_defaults(func=lambda a, c, cl, loc: cmd_contract_config(c, cl))

    p_advance = sub.add_parser("advance-block", help="Advance local sim block (for testing)")
    p_advance.add_argument("blocks", type=int, default=1, nargs="?", help="Blocks to advance")
    p_advance.set_defaults(func=lambda a, c, cl, loc: cmd_advance_block(c, loc, a.blocks))

    p_abi = sub.add_parser("abi-selectors", help="List view selectors")
    p_abi.set_defaults(func=lambda a, c, cl, loc: cmd_abi_selectors(c))

    p_simulate = sub.add_parser("simulate", help="Simulate queue+execute one mission (local)")
    p_simulate.add_argument("payload", nargs="?", default="sim_payload", help="Payload string")
    p_simulate.add_argument("--offset", type=int, default=50, help="Deadline block offset")
    p_simulate.set_defaults(func=lambda a, c, cl, loc: cmd_simulate(c, loc, a.payload, a.offset))

    p_chain = sub.add_parser("chain-info", help="Show chain id and name")
    p_chain.set_defaults(func=lambda a, c, cl, loc: cmd_chain_info(c))

    p_queue_demo = sub.add_parser("queue-demo", help="Queue N demo missions (local)")
    p_queue_demo.add_argument("count", type=int, nargs="?", default=3, help="Number of missions")
    p_queue_demo.add_argument("--deadline-blocks", type=int, default=100, help="Blocks until deadline")
    p_queue_demo.set_defaults(func=lambda a, c, cl, loc: cmd_queue_demo(c, loc, a.count, a.deadline_blocks))

    p_validate_cfg = sub.add_parser("validate-config", help="Validate current config")
    p_validate_cfg.set_defaults(func=lambda a, c, cl, loc: cmd_validate_config(c))

    p_stats = sub.add_parser("stats", help="Mission stats (local)")
    p_stats.set_defaults(func=lambda a, c, cl, loc: cmd_stats(c, loc))

    p_env = sub.add_parser("env-info", help="Show T2 env vars")
    p_env.set_defaults(func=lambda a, c, cl, loc: cmd_env_info(c))

    p_help_contract = sub.add_parser("help-contract", help="Help for contract interaction")
    p_help_contract.set_defaults(func=lambda a, c, cl, loc: cmd_help_contract(c))

    p_gas = sub.add_parser("gas-estimates", help="Show gas estimate stubs")
    p_gas.set_defaults(func=lambda a, c, cl, loc: cmd_gas_estimates(c))

    p_ver_full = sub.add_parser("version-full", help="Full version info as JSON")
    p_ver_full.set_defaults(func=lambda a, c, cl, loc: cmd_version_full(c))

    args = parser.parse_args()
    config = T2Config.load()
    config = t2_config_from_env(config)
    if args.no_banner:
        config.show_banner = False
    if getattr(args, "rpc", None):
        config.rpc_url = args.rpc
    if getattr(args, "contract", None):
        config.contract_address = args.contract
    config.save()

    client: Optional[T2ContractClient] = None
    if config.rpc_url:
        client = T2ContractClient(config.rpc_url, config.contract_address, config.chain_id)
        client.connect()
    local = T2LocalMissionStore()

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    if args.command == "config-set":
        return cmd_config_set(args, config)
    if args.command == "scan":
        run_scan_animation(args.duration)
        return 0

    return args.func(args, config, client, local)


if __name__ == "__main__":
    sys.exit(main())
