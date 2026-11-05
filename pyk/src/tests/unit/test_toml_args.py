from __future__ import annotations

import re
import tempfile
from os import PathLike
from typing import TYPE_CHECKING

from pyk.cli.pyk import PrintInput, ProveOptions, create_argument_parser, parse_toml_args

from .utils import TEST_DATA_DIR

if TYPE_CHECKING:
    from typing import Final

TEST_TOML: Final = TEST_DATA_DIR / 'pyk_toml_test.toml'


def change_in_toml(from_pattern: str, to_pattern: str) -> None:
    with open(str(TEST_TOML), 'r+') as f:
        content = f.read()
        content_new = re.sub(from_pattern, to_pattern, content, flags=re.M)
        f.seek(0)
        f.write(content_new)
        f.truncate()


def test_continue_when_default_toml_absent() -> None:
    parser = create_argument_parser()
    cmd_args = ['coverage', '.', str(TEST_TOML)]
    args = parser.parse_args(cmd_args)
    assert hasattr(args, 'config_file')
    assert str(args.config_file) == 'pyk.toml'
    assert hasattr(args, 'config_profile')
    assert str(args.config_profile) == 'default'
    args_dict = parse_toml_args(args)
    assert len(args_dict) == 0


def test_print_input() -> None:
    parser = create_argument_parser()
    cmd_args = ['print', '--config-file', str(TEST_TOML), '--input', 'kore-json', tempfile.gettempdir(), str(TEST_TOML)]
    args = parser.parse_args(cmd_args)
    args_dict = parse_toml_args(args)
    assert args_dict['input'] == PrintInput.KAST_JSON
    assert not args_dict['minimize']


def test_prove_booster_recover_mode_flag() -> None:
    parser = create_argument_parser()

    # The flag parses to True and is off (None at the arg layer, False in ProveOptions) by default
    args = parser.parse_args(['prove', str(TEST_TOML), '--booster-recover-mode'])
    assert args.booster_recover_mode is True
    args_default = parser.parse_args(['prove', str(TEST_TOML)])
    assert args_default.booster_recover_mode is None
    assert ProveOptions.default()['booster_recover_mode'] is False


def test_prove_legacy_kargs() -> None:
    parser = create_argument_parser()
    cmd_args = [
        'prove-legacy',
        '--config-file',
        str(TEST_TOML),
        tempfile.gettempdir(),
        str(TEST_TOML),
        str(TEST_TOML),
        'spec-module',
        'cmd_args',
    ]
    args = parser.parse_args(cmd_args)
    args_dict = parse_toml_args(args)
    assert len(args_dict['k_args']) == 2


def test_prove_legacy_profiles() -> None:
    parser = create_argument_parser()
    cmd_args = [
        'prove-legacy',
        '--config-file',
        str(TEST_TOML),
        '--config-profile',
        'verbose',
        tempfile.gettempdir(),
        str(TEST_TOML),
        str(TEST_TOML),
        'spec-module',
        'cmd_args',
    ]
    args = parser.parse_args(cmd_args)
    args_dict = parse_toml_args(args)
    assert len(args_dict['k_args']) == 2
    assert hasattr(args, 'verbose')
    assert 'verbose' in args_dict
    assert args_dict['verbose']


def test_toml_read() -> None:
    change_in_toml('definition = "(.*)"', f'definition = "{tempfile.gettempdir()}"')
    parser = create_argument_parser()
    cmd_args = ['coverage', '--config-file', str(TEST_TOML), '.', str(TEST_TOML), '--verbose']
    args = parser.parse_args(cmd_args)
    args_dict = parse_toml_args(args)
    assert 'output' in args_dict
    assert args_dict['output'] == 'default-file'
    assert isinstance(args_dict['definition_dir'], PathLike)
    assert hasattr(args, 'verbose')
    assert args.verbose


def test_toml_profiles() -> None:
    parser = create_argument_parser()
    cmd_args = [
        'coverage',
        '--config-file',
        str(TEST_TOML),
        '--config-profile',
        'a_profile',
        '.',
        str(TEST_TOML),
        '--verbose',
    ]
    args = parser.parse_args(cmd_args)
    args_dict = parse_toml_args(args)
    assert 'verbose' in args_dict
    assert args_dict['verbose']
    assert 'output' in args_dict
    assert args_dict['output'] == 'a-profile-file'
