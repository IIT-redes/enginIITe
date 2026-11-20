"""Command line of the platform.

    enginiite run config_CIGRE.yaml
    enginiite run path/to/case/config/config_CIGRE.yaml
    enginiite run config_CIGRE.yaml --workspace path/to/case
    enginiite run config_CIGRE.yaml --output path/to/results

A workspace is a folder with ``config/``, ``data_in/<network>/`` and, after a run, ``data_out/``. The run starts
inside it, so every input is read from it and every result is written to it, unless ``--output`` sends the results
to another folder. A short output folder avoids the path length limit of Windows.
"""
import argparse
import os
import sys
from pathlib import Path

CONFIG_FOLDER = 'config'


def resolve_run_target(config, workspace=None, cwd=None):
    """Return ``(workspace, configuration file name)`` for the argument given to ``enginiite run``.

    ``config`` is a file name, to be read from ``<workspace>/config``, or a path to a file that lives inside a
    folder called ``config``, in which case the workspace is the parent of that folder. Without ``workspace``
    the working folder is the workspace for a bare file name.
    """
    cwd = Path(cwd or os.getcwd()).resolve()
    config_path = Path(config)
    if config_path.suffix.lower() not in ('.yaml', '.yml'):
        raise ValueError(f'The configuration file must end in .yaml or .yml, got {config!r}.')
    if workspace is not None:
        workspace = Path(workspace)
        workspace = (workspace if workspace.is_absolute() else cwd / workspace).resolve()
        if not workspace.is_dir():
            raise FileNotFoundError(f'The workspace folder does not exist: {workspace}')

    if config_path.parent == Path('.'):
        workspace = workspace or cwd
        name = config_path.name
    else:
        full = (config_path if config_path.is_absolute() else cwd / config_path).resolve()
        if full.parent.name != CONFIG_FOLDER:
            raise ValueError(
                f'The configuration file {full} is not inside a folder called "{CONFIG_FOLDER}". '
                f'Put it in <workspace>/{CONFIG_FOLDER}/, or give only its file name together with --workspace.')
        if workspace is not None and full.parent.parent != workspace:
            raise ValueError(f'The configuration file {full} does not belong to the workspace {workspace}.')
        workspace = full.parent.parent
        name = full.name

    wanted = workspace / CONFIG_FOLDER / name
    if not wanted.is_file():
        raise FileNotFoundError(f'Configuration file not found: {wanted}. '
                                f'A workspace reads its configuration from {workspace / CONFIG_FOLDER}.')
    return workspace, name


def resolve_output(output, cwd=None):
    """Return the absolute results folder given with ``--output``, or ``None`` for the default ``data_out``."""
    if output is None:
        return None
    cwd = Path(cwd or os.getcwd()).resolve()
    folder = Path(output)
    folder = (folder if folder.is_absolute() else cwd / folder).resolve()
    if folder.exists() and not folder.is_dir():
        raise ValueError(f'The output path is a file, not a folder: {folder}')
    return folder


def build_parser():
    parser = argparse.ArgumentParser(prog='enginiite', description='Local flexibility market simulation platform.')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='run every scenario of a configuration file',
                              description='Run every scenario of a configuration file. Needs a Gurobi licence.')
    run.add_argument('config', help='configuration file name, or a path to a file inside a "config" folder')
    run.add_argument('--output', default=None,
                     help='folder for the results (default: data_out inside the workspace)')
    run.add_argument('--workspace', default=None,
                     help='folder with config/ and data_in/ (default: the folder of the path, or the working folder)')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        workspace, name = resolve_run_target(args.config, workspace=args.workspace)
        output = resolve_output(args.output)
    except (ValueError, FileNotFoundError) as error:
        print(f'enginiite: {error}', file=sys.stderr)
        return 2
    os.chdir(workspace)
    print(f'Workspace: {workspace}')
    from enginiite import workflow  # imported here so that --help does not load the solver and the plotting stack
    workflow.run(name, output=output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
