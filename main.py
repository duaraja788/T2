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
