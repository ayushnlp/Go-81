"""
Subprocess Tracker & Safe Reattachment for Project Go 81.
Tracks OS child processes with process creation timestamps (64-bit FILETIME on Windows,
/proc starttime on Linux) to prevent PID reuse vulnerabilities.
Durable stdout/stderr logging allows crash-resilient outcome inspection.
"""

import ctypes
import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Windows Win32 API Definitions for Process Tracking
IS_WINDOWS = sys.platform == "win32"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


if IS_WINDOWS:
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]


def get_process_creation_time(pid: int) -> Optional[float]:
    """
    Extracts deterministic process creation timestamp for a given PID.
    On Windows: Uses native kernel32 GetProcessTimes returning 64-bit FILETIME.
    On Linux: Reads /proc/{pid}/stat starttime or ctime.
    Returns None if process cannot be opened or does not exist.
    """
    if pid <= 0:
        return None

    if IS_WINDOWS:
        try:
            kernel32 = ctypes.windll.kernel32
            h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h_proc:
                return None
            creation = FILETIME()
            exit_t = FILETIME()
            kernel_t = FILETIME()
            user_t = FILETIME()
            ok = kernel32.GetProcessTimes(
                h_proc,
                ctypes.byref(creation),
                ctypes.byref(exit_t),
                ctypes.byref(kernel_t),
                ctypes.byref(user_t),
            )
            kernel32.CloseHandle(h_proc)
            if ok:
                # 64-bit FILETIME (100-nanosecond intervals since Jan 1, 1601)
                return float((creation.dwHighDateTime << 32) | creation.dwLowDateTime)
            return None
        except Exception as e:
            logger.debug(f"Error querying process times for PID {pid}: {e}")
            return None
    else:
        # POSIX / Linux implementation
        try:
            stat_path = f"/proc/{pid}/stat"
            if os.path.exists(stat_path):
                with open(stat_path, "r", encoding="utf-8") as f:
                    fields = f.read().split()
                    # Field 22 (index 21) is starttime in clock ticks
                    if len(fields) > 21:
                        return float(fields[21])
            # Fallback to directory creation/change time
            proc_dir = f"/proc/{pid}"
            if os.path.exists(proc_dir):
                return float(os.path.getctime(proc_dir))
        except Exception as e:
            logger.debug(f"Error reading proc info for PID {pid}: {e}")
            return None

    return None


def get_process_exit_code_windows(pid: int) -> Optional[int]:
    """
    Queries the exit code of a process on Windows using kernel32.GetExitCodeProcess.
    Returns None if process is still active or handle cannot be opened.
    """
    if not IS_WINDOWS or pid <= 0:
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            return None
        exit_code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(h_proc, ctypes.byref(exit_code))
        kernel32.CloseHandle(h_proc)
        if ok:
            if exit_code.value == STILL_ACTIVE:
                return None
            return int(exit_code.value)
    except Exception as e:
        logger.debug(f"Error checking exit code for PID {pid}: {e}")
    return None


def is_process_active(pid: int, expected_creation_time: Optional[float] = None) -> Tuple[bool, Optional[str]]:
    """
    Verifies if a process is alive and belongs to the exact recorded invocation.
    Detects and rejects PID reuse:
    - (True, None): Alive and creation timestamp matches.
    - (False, "PID_REUSE_DETECTED"): Process exists under PID, but creation time differs.
    - (False, "PROCESS_TERMINATED"): Process does not exist or has terminated.
    """
    if pid <= 0:
        return False, "INVALID_PID"

    current_creation_time = get_process_creation_time(pid)

    if current_creation_time is None:
        # Process does not exist or terminated
        return False, "PROCESS_TERMINATED"

    if expected_creation_time is not None:
        # Check creation time match with tolerance for floating precision
        diff = abs(current_creation_time - expected_creation_time)
        # FILETIME units are 100ns; allow tiny tolerance if converted or stored as float
        if diff > 1000.0:
            logger.warning(
                f"PID reuse detected for PID {pid}! "
                f"Expected creation {expected_creation_time}, actual {current_creation_time} (delta {diff}). "
                "Rejecting reattachment to foreign process."
            )
            return False, "PID_REUSE_DETECTED"

    # On Windows, double check exit code
    if IS_WINDOWS:
        exit_code = get_process_exit_code_windows(pid)
        if exit_code is not None:
            return False, "PROCESS_TERMINATED"

    return True, None


class SubprocessTracker:
    """
    Manages durable process lifecycle: spawning, output redirection,
    re-attachment, and crash-resilient verification.
    """

    def __init__(self, base_log_dir: str = ".system_generated/subprocesses"):
        self.base_log_dir = os.path.abspath(base_log_dir)
        os.makedirs(self.base_log_dir, exist_ok=True)

    def get_log_path(self, attempt_id: str) -> str:
        """Returns deterministic path to the subprocess log file."""
        safe_attempt = "".join(c for c in attempt_id if c.isalnum() or c in ("-", "_"))
        return os.path.join(self.base_log_dir, f"{safe_attempt}.log")

    def spawn(
        self,
        command: Union[str, List[str]],
        attempt_id: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Launches a child process with durable redirected output and captures exact creation time.
        """
        log_path = self.get_log_path(attempt_id)
        # Command fingerprint (SHA-256)
        cmd_str = command if isinstance(command, str) else " ".join(command)
        cmd_fingerprint = hashlib.sha256(cmd_str.encode("utf-8")).hexdigest()

        # Open durable log file for append
        log_file = open(log_path, "a", encoding="utf-8", errors="replace")
        log_file.write(f"--- [SUBPROCESS START attempt={attempt_id} time={time.time()}] ---\n")
        log_file.flush()

        try:
            # Launch subprocess
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                shell=isinstance(command, str),
            )
            pid = proc.pid
            creation_time = get_process_creation_time(pid) or time.time()

            logger.info(
                f"Tracked subprocess spawned: PID={pid}, attempt={attempt_id}, "
                f"creation_time={creation_time}, log={log_path}"
            )

            return {
                "pid": pid,
                "process_creation_time": creation_time,
                "log_path": log_path,
                "attempt_id": attempt_id,
                "cmd_fingerprint": cmd_fingerprint,
                "process": proc,
                "log_file_handle": log_file,
            }
        except Exception as e:
            log_file.write(f"\n--- [SPAWN ERROR: {str(e)}] ---\n")
            log_file.close()
            raise

    def read_bounded_log(self, log_path: str, max_bytes: int = 16384) -> str:
        """Reads up to max_bytes from the end of the log file, preserving bounded memory."""
        if not os.path.exists(log_path):
            return ""
        try:
            size = os.path.getsize(log_path)
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                if size > max_bytes:
                    f.seek(size - max_bytes)
                return f.read()
        except Exception as e:
            return f"[Error reading log: {e}]"

    def audit_subprocess_status(
        self,
        pid: Optional[int],
        process_creation_time: Optional[float],
        log_path: Optional[str],
        recorded_exit_code: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Audits the state of a subprocess across restarts or crashes:
        Returns status classification:
        - "ACTIVE": Process is verified running with exact creation timestamp.
        - "EXITED_CLEAN": Process terminated with verified exit code 0.
        - "EXITED_ERROR": Process terminated with verified non-zero exit code.
        - "PID_REUSE_DETECTED": PID exists but creation time differs.
        - "UNKNOWN_TERMINATED": Process is gone, exit code cannot be determined cleanly.
        - "NO_PROCESS_RECORD": No PID was recorded.
        """
        if pid is None or pid <= 0:
            return {"status": "NO_PROCESS_RECORD", "active": False}

        active, reason = is_process_active(pid, process_creation_time)

        if reason == "PID_REUSE_DETECTED":
            return {
                "status": "PID_REUSE_DETECTED",
                "active": False,
                "pid": pid,
                "error": "Process ID was reassigned to a foreign process.",
                "log_tail": self.read_bounded_log(log_path) if log_path else "",
            }

        if active:
            return {
                "status": "ACTIVE",
                "active": True,
                "pid": pid,
                "creation_time": process_creation_time,
                "log_tail": self.read_bounded_log(log_path) if log_path else "",
            }

        # Process has terminated
        # Check if we have an exit code from Windows or from log markers
        exit_code = recorded_exit_code
        if exit_code is None and IS_WINDOWS:
            exit_code = get_process_exit_code_windows(pid)

        # Inspect log file for completion markers if available
        log_tail = self.read_bounded_log(log_path) if log_path else ""
        if exit_code is None:
            if "--- [SUBPROCESS COMPLETED exit=0" in log_tail:
                exit_code = 0
            elif "--- [SUBPROCESS FAILED exit=" in log_tail:
                try:
                    marker = log_tail.split("--- [SUBPROCESS FAILED exit=")[-1].split("]")[0]
                    exit_code = int(marker)
                except Exception:
                    exit_code = 1

        if exit_code == 0:
            return {
                "status": "EXITED_CLEAN",
                "active": False,
                "pid": pid,
                "exit_code": 0,
                "log_tail": log_tail,
            }
        elif exit_code is not None:
            return {
                "status": "EXITED_ERROR",
                "active": False,
                "pid": pid,
                "exit_code": exit_code,
                "log_tail": log_tail,
            }
        else:
            # Process terminated with unknown outcome
            return {
                "status": "UNKNOWN_TERMINATED",
                "active": False,
                "pid": pid,
                "log_tail": log_tail,
                "error": "Process terminated without a verifiable exit code.",
            }

    async def run_tracked_subprocess(
        self,
        command: Union[str, List[str]],
        attempt_id: str,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        journal_service: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Executes a subprocess with real-time journal tracking and log capture.
        Records PID and creation time immediately, monitors execution, and updates journal on completion.
        """
        import asyncio
        spawn_info = self.spawn(command, attempt_id, cwd=cwd, env=env, timeout=timeout)
        pid = spawn_info["pid"]
        creation_time = spawn_info["process_creation_time"]
        log_path = spawn_info["log_path"]
        proc = spawn_info["process"]
        log_file = spawn_info["log_file_handle"]

        if journal_service:
            journal_service.record_running_process(attempt_id, pid, creation_time, log_path)

        loop = asyncio.get_running_loop()
        try:
            if timeout:
                returncode = await asyncio.wait_for(loop.run_in_executor(None, proc.wait), timeout=timeout)
            else:
                returncode = await loop.run_in_executor(None, proc.wait)

            log_file.write(f"\n--- [SUBPROCESS COMPLETED exit={returncode} time={time.time()}] ---\n")
            log_file.flush()
            log_file.close()

            log_tail = self.read_bounded_log(log_path)
            digest = hashlib.sha256(log_tail.encode("utf-8")).hexdigest()

            if returncode == 0:
                if journal_service:
                    journal_service.record_success(attempt_id, result_digest=digest, exit_code=0)
            else:
                if journal_service:
                    journal_service.record_failure(attempt_id, error_message=f"Process exited with {returncode}", exit_code=returncode)

            return {
                "success": returncode == 0,
                "exit_code": returncode,
                "output": log_tail,
                "pid": pid,
                "creation_time": creation_time,
                "log_path": log_path,
            }

        except asyncio.TimeoutError:
            proc.kill()
            log_file.write(f"\n--- [SUBPROCESS TIMEOUT time={time.time()}] ---\n")
            log_file.flush()
            log_file.close()
            if journal_service:
                journal_service.record_unknown_outcome(attempt_id, f"Subprocess timed out after {timeout}s")
                journal_service.record_reconciliation_required(attempt_id, "Subprocess timed out; side-effect outcome uncertain.")
            raise

        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            log_file.write(f"\n--- [SUBPROCESS EXCEPTION: {e}] ---\n")
            log_file.flush()
            log_file.close()
            if journal_service:
                journal_service.record_failure(attempt_id, error_message=str(e), exit_code=1)
            raise
