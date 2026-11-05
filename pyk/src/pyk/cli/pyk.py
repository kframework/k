from __future__ import annotations

import logging
from argparse import ArgumentParser, FileType
from enum import Enum
from typing import IO, TYPE_CHECKING, Any

import tomli

from ..ktool import TypeInferenceMode
from ..ktool.kompile import KompileBackend
from .args import (
    ConfigArgs,
    DefinitionOptions,
    DisplayOptions,
    KCLIArgs,
    KDefinitionOptions,
    KompileOptions,
    LoggingOptions,
    OutputFileOptions,
    SaveDirOptions,
    SpecOptions,
    WarningOptions,
)
from .utils import dir_path, file_path

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Callable, Iterable
    from pathlib import Path
    from typing import Final

_LOGGER: Final = logging.getLogger(__name__)


def generate_options(args: dict[str, Any]) -> LoggingOptions:
    command = args['command']
    match command:
        case 'json-to-kore':
            return JsonToKoreOptions(args)
        case 'kore-to-json':
            return KoreToJsonOptions(args)
        case 'coverage':
            return CoverageOptions(args)
        case 'graph-imports':
            return GraphImportsOptions(args)
        case 'rpc-kast':
            return RPCKastOptions(args)
        case 'rpc-print':
            return RPCPrintOptions(args)
        case 'print':
            return PrintOptions(args)
        case 'prove-legacy':
            return ProveLegacyOptions(args)
        case 'prove':
            return ProveOptions(args)
        case 'show':
            return ProveOptions(args)
        case 'kompile':
            return KompileCommandOptions(args)
        case 'kompilex':
            return KompileXCommandOptions(args)
        case 'run':
            return RunOptions(args)
        case 'parse-outer':
            return ParseOuterOptions(args)
        case _:
            raise ValueError(f'Unrecognized command: {command}')


def get_option_string_destination(command: str, option_string: str) -> str:
    option_string_destinations = {}
    match command:
        case 'json-to-kore':
            option_string_destinations = JsonToKoreOptions.from_option_string()
        case 'kore-to-json':
            option_string_destinations = KoreToJsonOptions.from_option_string()
        case 'coverage':
            option_string_destinations = CoverageOptions.from_option_string()
        case 'graph-imports':
            option_string_destinations = GraphImportsOptions.from_option_string()
        case 'rpc-kast':
            option_string_destinations = RPCKastOptions.from_option_string()
        case 'rpc-print':
            option_string_destinations = RPCPrintOptions.from_option_string()
        case 'print':
            option_string_destinations = PrintOptions.from_option_string()
        case 'prove-legacy':
            option_string_destinations = ProveLegacyOptions.from_option_string()
        case 'prove':
            option_string_destinations = ProveOptions.from_option_string()
        case 'kompile':
            option_string_destinations = KompileCommandOptions.from_option_string()
        case 'kompilex':
            option_string_destinations = KompileXCommandOptions.from_option_string()
        case 'run':
            option_string_destinations = RunOptions.from_option_string()

    return option_string_destinations.get(option_string, option_string.replace('-', '_'))


def get_argument_type_setter(command: str, option_string: str) -> Callable[[str], Any]:
    option_types = {}
    match command:
        case 'json-to-kore':
            option_types = JsonToKoreOptions.get_argument_type()
        case 'kore-to-json':
            option_types = KoreToJsonOptions.get_argument_type()
        case 'coverage':
            option_types = CoverageOptions.get_argument_type()
        case 'graph-imports':
            option_types = GraphImportsOptions.get_argument_type()
        case 'rpc-kast':
            option_types = RPCKastOptions.get_argument_type()
        case 'rpc-print':
            option_types = RPCPrintOptions.get_argument_type()
        case 'print':
            option_types = PrintOptions.get_argument_type()
        case 'prove-legacy':
            option_types = ProveLegacyOptions.get_argument_type()
        case 'prove':
            option_types = ProveOptions.get_argument_type()
        case 'kompile':
            option_types = KompileCommandOptions.get_argument_type()
        case 'run':
            option_types = RunOptions.get_argument_type()

    return option_types.get(option_string, (lambda x: x))


class PrintInput(Enum):
    KORE_JSON = 'kore-json'
    KAST_JSON = 'kast-json'


class JsonToKoreOptions(LoggingOptions): ...


class KoreToJsonOptions(LoggingOptions): ...


class CoverageOptions(DefinitionOptions, OutputFileOptions, LoggingOptions):
    coverage_file: IO[Any]

    @staticmethod
    def from_option_string() -> dict[str, str]:
        return (
            DefinitionOptions.from_option_string()
            | OutputFileOptions.from_option_string()
            | LoggingOptions.from_option_string()
        )

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return (
            DefinitionOptions.get_argument_type()
            | OutputFileOptions.get_argument_type()
            | LoggingOptions.get_argument_type()
            | {'coverage_file': FileType('r')}
        )


class GraphImportsOptions(DefinitionOptions, LoggingOptions):
    @staticmethod
    def from_option_string() -> dict[str, str]:
        return DefinitionOptions.from_option_string() | LoggingOptions.from_option_string()

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return DefinitionOptions.get_argument_type() | LoggingOptions.get_argument_type()


class RPCKastOptions(OutputFileOptions, LoggingOptions):
    reference_request_file: IO[Any]
    response_file: IO[Any]

    @staticmethod
    def from_option_string() -> dict[str, str]:
        return OutputFileOptions.from_option_string() | LoggingOptions.from_option_string()

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return (
            OutputFileOptions.get_argument_type()
            | LoggingOptions.get_argument_type()
            | {'reference_request_file': FileType('r'), 'response_file': FileType('r')}
        )


class RPCPrintOptions(DefinitionOptions, OutputFileOptions, LoggingOptions):
    input_file: IO[Any]

    @staticmethod
    def from_option_string() -> dict[str, str]:
        return (
            DefinitionOptions.from_option_string()
            | OutputFileOptions.from_option_string()
            | LoggingOptions.from_option_string()
        )

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return (
            OutputFileOptions.get_argument_type() | LoggingOptions.get_argument_type() | {'input_file': FileType('r')}
        )


class PrintOptions(DefinitionOptions, OutputFileOptions, DisplayOptions, LoggingOptions):
    term: IO[Any]
    input: PrintInput
    minimize: bool

    @staticmethod
    def default() -> dict[str, Any]:
        return {
            'input': PrintInput.KAST_JSON,
        }

    @staticmethod
    def from_option_string() -> dict[str, str]:
        return (
            DefinitionOptions.from_option_string()
            | OutputFileOptions.from_option_string()
            | DisplayOptions.from_option_string()
            | LoggingOptions.from_option_string()
        )

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return (
            DefinitionOptions.get_argument_type()
            | OutputFileOptions.get_argument_type()
            | DisplayOptions.get_argument_type()
            | LoggingOptions.get_argument_type()
            | {'term': FileType('r'), 'input': PrintInput}
        )


class ProveLegacyOptions(DefinitionOptions, OutputFileOptions, LoggingOptions):
    main_file: Path
    spec_file: Path
    spec_module: str
    k_args: Iterable[str]

    @staticmethod
    def default() -> dict[str, Any]:
        return {
            'k_args': [],
        }

    @staticmethod
    def from_option_string() -> dict[str, str]:
        return (
            DefinitionOptions.from_option_string()
            | OutputFileOptions.from_option_string()
            | LoggingOptions.from_option_string()
            | {'kArgs': 'k_args'}
        )

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return (
            DefinitionOptions.get_argument_type()
            | OutputFileOptions.get_argument_type()
            | LoggingOptions.get_argument_type()
        )


class KompileCommandOptions(LoggingOptions, WarningOptions, KDefinitionOptions, KompileOptions):
    definition_dir: Path | None
    main_file: str
    backend: KompileBackend
    type_inference_mode: TypeInferenceMode | None

    @staticmethod
    def default() -> dict[str, Any]:
        return {
            'definition_dir': None,
            'backend': KompileBackend.LLVM,
            'type_inference_mode': None,
        }

    @staticmethod
    def from_option_string() -> dict[str, str]:
        return (
            KDefinitionOptions.from_option_string()
            | KompileOptions.from_option_string()
            | LoggingOptions.from_option_string()
            | {'definition': 'definition_dir'}
        )

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return (
            KDefinitionOptions.get_argument_type()
            | KompileOptions.get_argument_type()
            | LoggingOptions.get_argument_type()
            | {'definition': dir_path, 'backend': KompileBackend, 'type-inference-mode': TypeInferenceMode}
        )


class KompileXCommandOptions(KompileCommandOptions):
    pre_parsed_prelude: IO[Any] | None

    @staticmethod
    def default() -> dict[str, Any]:
        return {
            'pre_parsed_prelude': None,
        }


class ProveOptions(LoggingOptions, SpecOptions, SaveDirOptions):
    definition_dir: Path | None
    type_inference_mode: TypeInferenceMode | None
    failure_info: bool
    kore_rpc_command: str | Iterable[str] | None
    max_depth: int | None
    max_iterations: int | None
    step_timeout: int | None
    assume_defined: bool
    show_kcfg: bool
    haskell_logging: bool
    booster_recover_mode: bool

    @staticmethod
    def default() -> dict[str, Any]:
        return {
            'definition_dir': None,
            'type_inference_mode': None,
            'failure_info': False,
            'kore_rpc_command': None,
            'max_depth': None,
            'max_iterations': None,
            'step_timeout': None,
            'assume_defined': False,
            'show_kcfg': False,
            'haskell_logging': False,
            'booster_recover_mode': False,
        }

    @staticmethod
    def from_option_string() -> dict[str, str]:
        return (
            KDefinitionOptions.from_option_string()
            | KompileOptions.from_option_string()
            | LoggingOptions.from_option_string()
            | {'definition': 'definition_dir'}
        )

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return (
            KDefinitionOptions.get_argument_type()
            | KompileOptions.get_argument_type()
            | LoggingOptions.get_argument_type()
            | {'definition': dir_path, 'type-inference-mode': TypeInferenceMode}
        )


class RunOptions(LoggingOptions):
    pgm_file: str
    definition_dir: Path | None
    parser: str | None

    @staticmethod
    def default() -> dict[str, Any]:
        return {
            'definition_dir': None,
            'parser': None,
        }

    @staticmethod
    def from_option_string() -> dict[str, str]:
        return LoggingOptions.from_option_string() | {'definition': 'definition_dir'}

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return LoggingOptions.get_argument_type() | {'definition': dir_path}


class ParseOuterOptions(LoggingOptions, KDefinitionOptions):
    main_file: Path
    output_file: IO[Any]

    @staticmethod
    def get_argument_type() -> dict[str, Callable]:
        return (
            LoggingOptions.get_argument_type()
            | KDefinitionOptions.get_argument_type()
            | {'main_file': file_path, 'output_file': FileType('w')}
        )


def create_argument_parser() -> ArgumentParser:
    k_cli_args = KCLIArgs()
    config_args = ConfigArgs()

    pyk_args = ArgumentParser()
    pyk_args_command = pyk_args.add_subparsers(dest='command', required=True)

    print_args = pyk_args_command.add_parser(
        'print',
        help='Pretty print a term.',
        parents=[k_cli_args.logging_args, k_cli_args.display_args, config_args.config_args],
    )
    print_args.add_argument('definition_dir', type=dir_path, help='Path to definition directory.')
    print_args.add_argument('term', type=FileType('r'), help='Input term (in format specified with --input).')
    print_args.add_argument('--input', type=PrintInput, choices=list(PrintInput))
    print_args.add_argument('--output-file', type=FileType('w'))

    rpc_print_args = pyk_args_command.add_parser(
        'rpc-print',
        help='Pretty-print an RPC request/response',
        parents=[k_cli_args.logging_args, config_args.config_args],
    )
    rpc_print_args.add_argument('definition_dir', type=dir_path, help='Path to definition directory.')
    rpc_print_args.add_argument(
        'input_file',
        type=FileType('r'),
        help='An input file containing the JSON RPC request or response with KoreJSON payload.',
    )
    rpc_print_args.add_argument('--output-file', type=FileType('w'))

    rpc_kast_args = pyk_args_command.add_parser(
        'rpc-kast',
        help='Convert an "execute" JSON RPC response to a new "execute" or "simplify" request, copying parameters from a reference request.',
        parents=[k_cli_args.logging_args, config_args.config_args],
    )
    rpc_kast_args.add_argument(
        'reference_request_file',
        type=FileType('r'),
        help='An input file containing a JSON RPC request to server as a reference for the new request.',
    )
    rpc_kast_args.add_argument(
        'response_file',
        type=FileType('r'),
        help='An input file containing a JSON RPC response with KoreJSON payload.',
    )
    rpc_kast_args.add_argument('--output-file', type=FileType('w'))

    prove_legacy_args = pyk_args_command.add_parser(
        'prove-legacy',
        help='Prove an input specification (using kprovex).',
        parents=[k_cli_args.logging_args, config_args.config_args],
    )
    prove_legacy_args.add_argument('definition_dir', type=dir_path, help='Path to definition directory.')
    prove_legacy_args.add_argument('main_file', type=str, help='Main file used for kompilation.')
    prove_legacy_args.add_argument('spec_file', type=str, help='File with the specification module.')
    prove_legacy_args.add_argument('spec_module', type=str, help='Module with claims to be proven.')
    prove_legacy_args.add_argument('--output-file', type=FileType('w'))
    prove_legacy_args.add_argument('kArgs', nargs='*', help='Arguments to pass through to K invocation.')

    kompile_args = pyk_args_command.add_parser(
        'kompile',
        help='Kompile the K specification.',
        parents=[
            k_cli_args.logging_args,
            k_cli_args.warning_args,
            k_cli_args.definition_args,
            k_cli_args.kompile_args,
            config_args.config_args,
        ],
    )
    kompile_args.add_argument('main_file', type=str, help='File with the specification module.')

    kompilex_args = pyk_args_command.add_parser(
        'kompilex',
        help='Kompile the K specification.',
        parents=[
            k_cli_args.logging_args,
            k_cli_args.warning_args,
            k_cli_args.definition_args,
            k_cli_args.kompile_args,
            config_args.config_args,
        ],
    )
    kompilex_args.add_argument('main_file', type=str, help='File with the specification module.')
    kompilex_args.add_argument(
        '--pre-parsed-prelude',
        dest='pre_parsed_prelude',
        type=FileType('r'),
        help='File with outer parsed modules from the prelude in JSON',
    )

    run_args = pyk_args_command.add_parser(
        'run',
        help='Run a given program using the K definition.',
        parents=[k_cli_args.logging_args, config_args.config_args],
    )
    run_args.add_argument('pgm_file', type=str, help='File program to run in it.')
    run_args.add_argument('--definition', type=dir_path, dest='definition_dir', help='Path to definition to use.')
    run_args.add_argument('--parser', type=str, help='Command to use as a custom parser.')

    prove_args = pyk_args_command.add_parser(
        'prove',
        help='Prove an input specification (using RPC based prover).',
        parents=[k_cli_args.logging_args, k_cli_args.spec_args, config_args.config_args],
    )

    prove_args.add_argument(
        '--failure-info',
        default=None,
        action='store_true',
        help='Print out more information about proof failures.',
    )
    prove_args.add_argument(
        '--show-kcfg',
        default=None,
        action='store_true',
        help='Display the resulting proof KCFG.',
    )
    prove_args.add_argument(
        '--max-depth',
        type=int,
        help='Maximum number of steps to take in symbolic execution per basic block.',
    )
    prove_args.add_argument(
        '--max-iterations',
        type=int,
        help='Maximum number of KCFG explorations to take in attempting to discharge proof.',
    )
    prove_args.add_argument(
        '--step-timeout',
        dest='step_timeout',
        type=int,
        default=None,
        help=(
            'Per-step wall-clock budget in whole seconds (floored at 1). When a symbolic-execution step'
            ' exceeds it, the step is interrupted, its execution depth is halved, and it is retried;'
            ' proving stops once the depth cannot be reduced further. Omit to disable the timeout.'
        ),
    )
    prove_args.add_argument(
        '--kore-rpc-command',
        dest='kore_rpc_command',
        type=str,
        default=None,
        help='Custom command to start RPC server.',
    )
    prove_args.add_argument(
        '--haskell-logging',
        dest='haskell_logging',
        default=None,
        action='store_true',
        help=(
            "Request the haskell-backend's per-request log bundle on every RPC and write it to"
            ' <save-directory>/haskell-logs/<request_id>.jsonl (one JSON value per line).'
            ' Requires --save-directory.'
        ),
    )
    prove_args.add_argument(
        '--booster-recover-mode',
        dest='booster_recover_mode',
        default=None,
        action='store_true',
        help=(
            'Run the reachability prover booster-only, escalating to Kore (re-simplification then'
            ' the Kore operation) only where booster cannot make progress, and record in the KCFG'
            ' exactly where Kore did work (variants + kore_handoffs) for diagnostic attribution.'
        ),
    )

    show_args = pyk_args_command.add_parser(
        'show',
        help='Display the status of a given proof.',
        parents=[k_cli_args.logging_args, k_cli_args.spec_args],
    )
    show_args.add_argument(
        '--failure-info',
        default=None,
        action='store_true',
        help='Print out more information about proof failures.',
    )
    graph_imports_args = pyk_args_command.add_parser(
        'graph-imports',
        help='Graph the imports of a given definition.',
        parents=[k_cli_args.logging_args, config_args.config_args],
    )
    graph_imports_args.add_argument('definition_dir', type=dir_path, help='Path to definition directory.')

    coverage_args = pyk_args_command.add_parser(
        'coverage',
        help='Convert coverage file to human readable log.',
        parents=[k_cli_args.logging_args, config_args.config_args],
    )
    coverage_args.add_argument('definition_dir', type=dir_path, help='Path to definition directory.')
    coverage_args.add_argument('coverage_file', type=FileType('r'), help='Coverage file to build log for.')
    coverage_args.add_argument('-o', '--output', type=FileType('w'))

    pyk_args_command.add_parser(
        'kore-to-json', help='Convert textual KORE to JSON', parents=[k_cli_args.logging_args, config_args.config_args]
    )

    pyk_args_command.add_parser(
        'json-to-kore', help='Convert JSON to textual KORE', parents=[k_cli_args.logging_args, config_args.config_args]
    )

    parse_outer_args = pyk_args_command.add_parser(
        'parse-outer',
        help='Parse an outer K definition into JSON',
        parents=[k_cli_args.logging_args, k_cli_args.definition_args, config_args.config_args],
    )
    parse_outer_args.add_argument('main_file', type=file_path, help='File with the K definition')
    parse_outer_args.add_argument('--output-file', type=FileType('w'), help='Write output to file instead of stdout.')

    return pyk_args


def parse_toml_args(
    args: Namespace,
    option_destinations: Callable[[str, str], str] = get_option_string_destination,
    arg_type_getter: Callable[[str, str], Callable[[str], Any]] = get_argument_type_setter,
) -> dict[str, Any]:
    def get_profile(toml_profile: dict[str, Any], profile_list: list[str]) -> dict[str, Any]:
        if len(profile_list) == 0 or profile_list[0] not in toml_profile:
            return {k: v for k, v in toml_profile.items() if type(v) is not dict}
        elif len(profile_list) == 1:
            active_profile = {k: v for k, v in toml_profile.get(profile_list[0], {}).items() if type(v) is not dict}
            default_profile = {k: v for k, v in toml_profile.get('default', {}).items() if type(v) is not dict}
            return {**default_profile, **active_profile}
        return get_profile(toml_profile[profile_list[0]], profile_list[1:])

    toml_args: dict[str, Any] = {}
    if not hasattr(args, 'config_file') or not args.config_file.is_file():
        return {}

    with open(args.config_file, 'rb') as config_file:
        try:
            toml_args = tomli.load(config_file)
        except tomli.TOMLDecodeError:
            _LOGGER.error(
                'Input config file is not in TOML format, ignoring the file and carrying on with the provided command line agruments'
            )

    toml_args = (
        get_profile(toml_args[args.command], args.config_profile.split('.')) if args.command in toml_args else {}
    )

    toml_adj_args: dict[str, Any] = {}
    for k, v in toml_args.items():
        opt_string = option_destinations(args.command, k)
        val = arg_type_getter(args.command, k)(v)
        if opt_string[:3] == 'no-' or opt_string[:3] == 'no_':
            toml_adj_args[opt_string[3:]] = not val
        elif k == 'optimization-level':
            level = toml_args[k] if toml_args[k] >= 0 else 0
            level = level if toml_args[k] <= 3 else 3
            toml_adj_args['o' + str(level)] = True
        else:
            toml_adj_args[opt_string] = val

    return toml_adj_args
