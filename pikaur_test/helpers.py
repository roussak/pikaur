""" This file is licensed under GPLv3, see https://www.gnu.org/licenses/ """

import sys
import os
import tempfile
from subprocess import Popen
from typing import Optional, List, NoReturn

from pikaur.main import main
from pikaur.args import CachedArgs, parse_args  # pylint:disable=no-name-in-module
from pikaur.pacman import PackageDB  # pylint:disable=no-name-in-module


TEST_DIR = os.path.dirname(os.path.realpath(__file__))


class TestPopen(Popen):
    stderr_text: Optional[str] = None
    stdout_text: Optional[str] = None


def spawn(cmd: List[str], **kwargs) -> TestPopen:
    with tempfile.TemporaryFile() as out_file:
        with tempfile.TemporaryFile() as err_file:
            proc = TestPopen(cmd, stdout=out_file, stderr=err_file, **kwargs)
            proc.communicate()
            out_file.seek(0)
            err_file.seek(0)
            proc.stdout_text = out_file.read().decode('utf-8')
            proc.stderr_text = err_file.read().decode('utf-8')
            return proc


def color_line(line: str, color_number: int) -> str:
    result = ''
    if color_number >= 8:
        result += "\033[0;1m"
        color_number -= 8
    result += f"\033[03{color_number}m{line}"
    # reset font:
    result += "\033[0;0m"
    return result


class CmdResult:

    def __init__(
            self,
            returncode: Optional[int] = None,
            stdout: Optional[str] = None,
            stderr: Optional[str] = None
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __repr__(self) -> str:
        return (
            f'<{self.returncode}>:\n'
            f'{self.stderr}\n'
            f'{self.stdout}\n'
        )

    def __eq__(self, other) -> bool:
        return ((
            self.stdout == other.stdout
        ) and (
            self.stderr == other.stderr
        ) and (
            self.returncode == other.returncode
        ))


class InterceptSysOutput():

    stdout_text: str
    stderr_text: str

    def __init__(self, capture_stdout=True, capture_stderr=False) -> None:
        self.capture_stdout = capture_stdout
        self.capture_stderr = capture_stderr

    def __enter__(self) -> 'InterceptSysOutput':
        self.out_file = tempfile.TemporaryFile('w+', encoding='UTF-8')
        self.err_file = tempfile.TemporaryFile('w+', encoding='UTF-8')
        self.out_file.isatty = lambda: False  # type: ignore
        self.err_file.isatty = lambda: False  # type: ignore

        self._real_stdout = sys.stdout
        self._real_stderr = sys.stderr
        if self.capture_stdout:
            sys.stdout = self.out_file  # type: ignore
        if self.capture_stderr:
            sys.stderr = self.err_file  # type: ignore

        return self

    def __exit__(self, *_exc_details) -> None:
        sys.stdout = self._real_stdout
        sys.stderr = self._real_stderr

        self.out_file.flush()
        self.err_file.flush()
        self.out_file.seek(0)
        self.err_file.seek(0)
        self.stdout_text = self.out_file.read()
        self.stderr_text = self.err_file.read()
        self.out_file.close()
        self.err_file.close()


def pikaur(
        cmd: str, capture_stdout=True, capture_stderr=False, fake_makepkg=False
) -> CmdResult:
    returncode: Optional[int] = None
    stdout_text: Optional[str] = None
    stderr_text: Optional[str] = None

    PackageDB.discard_local_cache()

    class FakeExit(Exception):
        pass

    def fake_exit(code: Optional[int] = 0) -> NoReturn:
        nonlocal returncode
        returncode = code
        raise FakeExit()

    # re-parse args:
    sys.argv = ['pikaur'] + cmd.split(' ') + (
        [
            '--noconfirm',
        ] if '-S ' in cmd else []
    ) + (
        [
            '--makepkg-path=' + os.path.join(TEST_DIR, 'fake_makepkg'),
        ] if fake_makepkg else []
    )
    CachedArgs.args = None  # pylint:disable=protected-access
    parse_args()
    # monkey-patch to force always uncolored output:
    CachedArgs.args.color = 'never'  # type: ignore # pylint:disable=protected-access
    print(color_line('\n => ', 10) + ' '.join(sys.argv))

    _real_exit = sys.exit
    sys.exit = fake_exit  # type: ignore

    intercepted: InterceptSysOutput
    with InterceptSysOutput(
            capture_stderr=capture_stderr,
            capture_stdout=capture_stdout
    ) as _intercepted:

        try:
            main()
        except FakeExit:
            pass
        intercepted = _intercepted

    stdout_text = intercepted.stdout_text
    stderr_text = intercepted.stderr_text

    sys.exit = _real_exit

    return CmdResult(
        returncode=returncode,
        stdout=stdout_text,
        stderr=stderr_text,
    )


def pacman(cmd: str) -> CmdResult:
    args = ['pacman'] + cmd.split(' ')
    proc = spawn(args)
    return CmdResult(
        returncode=proc.returncode,
        stdout=proc.stdout_text,
        stderr=proc.stderr_text,
    )


def assert_installed(pkg_name: str) -> None:
    assert(
        pacman(f'-Qi {pkg_name}').returncode == 0
    )


def assert_not_installed(pkg_name: str) -> None:
    assert(
        pacman(f'-Qi {pkg_name}').returncode == 1
    )


def assert_provided_by(dep_name: str, provider_name: str) -> None:
    cmd_result = pacman(f'-Qsq {dep_name}').stdout
    assert(
        cmd_result and (cmd_result.strip() == provider_name)
    )


def remove_packages(*pkg_names: str) -> None:
    pikaur('-Rs --noconfirm ' + ' '.join(pkg_names))
    for name in pkg_names:
        assert_not_installed(name)
