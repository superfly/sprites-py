#!/usr/bin/env python3
"""
Test CLI for Sprites Python SDK

Usage:
    python -m test_cli [options] <command> [command-options]

Global Options:
    -base-url <url>       Base URL for the sprite API (default: https://api.sprites.dev)
    -sprite <name>        Sprite name (required for most commands)
    -dir <path>           Working directory for filesystem operations

Commands:
    create <name>         Create a new sprite
    destroy <name>        Destroy a sprite
    list                  List all sprites

    # Filesystem commands (require -sprite)
    fs-read -path <path>                          Read file contents
    fs-write -path <path> -content <content>      Write content to file
    fs-list -path <path>                          List directory contents
    fs-stat -path <path>                          Get file/directory stats
    fs-mkdir -path <path> [-parents]              Create directory
    fs-rm -path <path> [-recursive]               Remove file or directory
    fs-rename -old <path> -new <path>             Rename/move file or directory
    fs-copy -src <path> -dst <path>               Copy file or directory
    fs-chmod -path <path> -mode <mode>            Change file permissions

    # Policy commands (require -sprite)
    policy get                                    Get network policy
    policy set <json>                             Set network policy

    # Checkpoint commands (require -sprite)
    checkpoint list                               List checkpoints
    checkpoint create <comment>                   Create checkpoint
    checkpoint get <id>                           Get checkpoint details
"""

import json
import os
import sys
from typing import Optional, Dict, Any, List

# Add parent directory to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sprites import SpritesClient, FilesystemError, NetworkPolicy, PolicyRule
from sprites.exceptions import ExitError, TimeoutError as SpriteTimeoutError


def parse_duration(s: str) -> Optional[float]:
    """Parse a Go-style duration string (e.g., '10s', '5m', '1h') to seconds."""
    if not s or s == "0":
        return None

    s = s.strip()
    total = 0.0
    current_num = ""

    i = 0
    while i < len(s):
        c = s[i]
        if c.isdigit() or c == ".":
            current_num += c
        else:
            if current_num:
                num = float(current_num)
                if c == "h":
                    total += num * 3600
                elif c == "m":
                    # Check for 'ms' (milliseconds)
                    if i + 1 < len(s) and s[i + 1] == "s":
                        total += num / 1000
                        i += 1
                    else:
                        total += num * 60
                elif c == "s":
                    total += num
                current_num = ""
        i += 1

    # Handle plain number (assume seconds)
    if current_num:
        total += float(current_num)

    return total if total > 0 else None


def parse_env(env_str: str) -> Dict[str, str]:
    """Parse comma-separated key=value pairs."""
    if not env_str:
        return {}
    result = {}
    for pair in env_str.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            result[key] = value
    return result


def parse_args(argv: List[str]) -> tuple[Dict[str, Any], List[str]]:
    """Parse Go-style command line arguments.

    Returns (options, remaining_args) where options contains global flags
    and remaining_args contains the command and its arguments.
    """
    options: Dict[str, Any] = {
        "base_url": os.environ.get("SPRITES_BASE_URL", "https://api.sprites.dev"),
        "sprite": None,
        "dir": None,
        "json": False,
        "output": "stdout",  # Output mode: stdout, combined, exit-code
        "timeout": None,
        "tty": False,
        "tty_rows": 24,
        "tty_cols": 80,
        "env": None,
    }

    args: List[str] = []
    i = 1  # Skip script name

    while i < len(argv):
        arg = argv[i]

        if arg == "-base-url":
            i += 1
            options["base_url"] = argv[i]
        elif arg == "-sprite":
            i += 1
            options["sprite"] = argv[i]
        elif arg == "-dir":
            i += 1
            options["dir"] = argv[i]
        elif arg == "-output":
            i += 1
            options["output"] = argv[i]
        elif arg == "-timeout":
            i += 1
            options["timeout"] = argv[i]
        elif arg == "-tty":
            options["tty"] = True
        elif arg == "-tty-rows":
            i += 1
            options["tty_rows"] = int(argv[i])
        elif arg == "-tty-cols":
            i += 1
            options["tty_cols"] = int(argv[i])
        elif arg == "-env":
            i += 1
            options["env"] = argv[i]
        elif arg == "-log-target":
            i += 1
            options["log_target"] = argv[i]
        elif arg == "-json":
            options["json"] = True
        elif arg in ("-help", "--help"):
            print(__doc__)
            sys.exit(0)
        elif not arg.startswith("-"):
            # Collect remaining args as command + args
            args = argv[i:]
            break
        else:
            # Unknown flag - might be command-specific
            args = argv[i:]
            break

        i += 1

    return options, args


def parse_fs_flags(args: List[str]) -> Dict[str, Any]:
    """Parse filesystem command flags (Go-style)."""
    flags: Dict[str, Any] = {
        "path": None,
        "content": None,
        "parents": False,
        "recursive": False,
        "old": None,
        "new": None,
        "src": None,
        "dst": None,
        "mode": None,
    }

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-path":
            i += 1
            flags["path"] = args[i] if i < len(args) else None
        elif arg == "-content":
            i += 1
            flags["content"] = args[i] if i < len(args) else None
        elif arg == "-parents":
            flags["parents"] = True
        elif arg == "-recursive":
            flags["recursive"] = True
        elif arg == "-old":
            i += 1
            flags["old"] = args[i] if i < len(args) else None
        elif arg == "-new":
            i += 1
            flags["new"] = args[i] if i < len(args) else None
        elif arg == "-src":
            i += 1
            flags["src"] = args[i] if i < len(args) else None
        elif arg == "-dst":
            i += 1
            flags["dst"] = args[i] if i < len(args) else None
        elif arg == "-mode":
            i += 1
            flags["mode"] = args[i] if i < len(args) else None
        i += 1

    return flags


def get_client(base_url: str) -> SpritesClient:
    """Get a SpritesClient using environment variables."""
    token = os.environ.get("SPRITES_TOKEN")
    if not token:
        print("Error: SPRITES_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)

    return SpritesClient(token=token, base_url=base_url)


def cmd_create(client: SpritesClient, args: List[str]) -> None:
    """Create a new sprite."""
    if len(args) < 1:
        print("Error: sprite name is required for create command", file=sys.stderr)
        sys.exit(1)

    sprite = client.create_sprite(args[0])
    print(f"Created sprite: {sprite.name}")


def cmd_destroy(client: SpritesClient, args: List[str]) -> None:
    """Destroy a sprite."""
    if len(args) < 1:
        print("Error: sprite name is required for destroy command", file=sys.stderr)
        sys.exit(1)

    client.destroy_sprite(args[0])
    print(f"Destroyed sprite: {args[0]}")


def cmd_list(client: SpritesClient) -> None:
    """List all sprites."""
    result = client.list_sprites()
    for sprite_info in result.sprites:
        print(f"{sprite_info.name} ({sprite_info.status})")


def cmd_fs_read(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """Read file contents."""
    path = flags.get("path")
    if not path:
        print("Error: -path is required for fs-read command", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    file_path = fs / path

    try:
        content = file_path.read_text()
        print(content, end="")
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fs_write(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """Write content to file."""
    path = flags.get("path")
    if not path:
        print("Error: -path is required for fs-write command", file=sys.stderr)
        sys.exit(1)

    content = flags.get("content") or ""

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    file_path = fs / path

    try:
        file_path.write_text(content)
        print(json.dumps({"status": "written", "path": path}))
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fs_list(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """List directory contents."""
    path = flags.get("path") or "."

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    dir_path = fs / path

    try:
        entries = []
        for entry in dir_path.iterdir():
            try:
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "isDirectory": stat.is_dir,
                    "isFile": not stat.is_dir,
                })
            except FilesystemError:
                entries.append({
                    "name": entry.name,
                })
        print(json.dumps(entries, indent=2))
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fs_stat(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """Get file/directory stats."""
    path = flags.get("path")
    if not path:
        print("Error: -path is required for fs-stat command", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    file_path = fs / path

    try:
        stat = file_path.stat()
        print(json.dumps({
            "size": stat.size,
            "mode": str(oct(stat.mode))[2:],  # Convert to octal string
            "mtime": stat.mod_time.isoformat(),
            "isDirectory": stat.is_dir,
            "isFile": not stat.is_dir,
        }, indent=2))
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fs_mkdir(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """Create directory."""
    path = flags.get("path")
    if not path:
        print("Error: -path is required for fs-mkdir command", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    dir_path = fs / path

    try:
        dir_path.mkdir(parents=flags.get("parents", False))
        print(json.dumps({"status": "created", "path": path}))
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fs_rm(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """Remove file or directory."""
    path = flags.get("path")
    if not path:
        print("Error: -path is required for fs-rm command", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    file_path = fs / path

    try:
        if flags.get("recursive"):
            file_path.rmtree()
        else:
            file_path.unlink(missing_ok=True)
        print(json.dumps({"status": "removed", "path": path}))
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fs_rename(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """Rename/move file or directory."""
    old_path = flags.get("old")
    new_path = flags.get("new")
    if not old_path or not new_path:
        print("Error: -old and -new are required for fs-rename command", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    source = fs / old_path
    dest = fs / new_path

    try:
        source.rename(dest)
        print(json.dumps({"status": "renamed", "source": old_path, "dest": new_path}))
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fs_copy(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """Copy file or directory."""
    src = flags.get("src")
    dst = flags.get("dst")
    if not src or not dst:
        print("Error: -src and -dst are required for fs-copy command", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    source = fs / src
    dest = fs / dst

    try:
        source.copy_to(dest, recursive=flags.get("recursive", True))
        print(json.dumps({"status": "copied", "source": src, "dest": dst}))
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fs_chmod(client: SpritesClient, sprite_name: str, workdir: str, flags: Dict[str, Any]) -> None:
    """Change file permissions."""
    path = flags.get("path")
    mode_str = flags.get("mode")
    if not path or not mode_str:
        print("Error: -path and -mode are required for fs-chmod command", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    fs = sprite.filesystem(workdir or "/")
    file_path = fs / path

    try:
        mode = int(mode_str, 8)
        file_path.chmod(mode, recursive=flags.get("recursive", False))
        print(json.dumps({"status": "chmod", "path": path, "mode": mode_str}))
    except FilesystemError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_policy_get(client: SpritesClient, sprite_name: str) -> None:
    """Get network policy."""
    sprite = client.sprite(sprite_name)
    policy = sprite.get_network_policy()
    rules = []
    for rule in policy.rules:
        r = {}
        if rule.domain:
            r["domain"] = rule.domain
        if rule.action:
            r["action"] = rule.action
        if rule.include:
            r["include"] = rule.include
        rules.append(r)
    print(json.dumps({"rules": rules}, indent=2))


def cmd_policy_set(client: SpritesClient, sprite_name: str, args: List[str]) -> None:
    """Set network policy."""
    if len(args) < 1:
        print("Error: policy JSON is required", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(args[0])

        # Validate that 'rules' key is present (server requires it)
        if "rules" not in data:
            print("Error: missing required key: rules", file=sys.stderr)
            sys.exit(1)

        rules = []
        for r in data["rules"]:
            rules.append(PolicyRule(
                domain=r.get("domain"),
                action=r.get("action"),
                include=r.get("include"),
            ))
        policy = NetworkPolicy(rules=rules)
        sprite = client.sprite(sprite_name)
        sprite.update_network_policy(policy)
        print(json.dumps({"status": "updated"}))
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_checkpoint_list(client: SpritesClient, sprite_name: str, as_json: bool) -> None:
    """List checkpoints."""
    sprite = client.sprite(sprite_name)
    checkpoints = sprite.list_checkpoints()

    if as_json:
        result = []
        for cp in checkpoints:
            result.append({
                "id": cp.id,
                "create_time": cp.create_time.isoformat(),
                "comment": cp.comment,
            })
        print(json.dumps(result, indent=2))
    else:
        for cp in checkpoints:
            comment = f" - {cp.comment}" if cp.comment else ""
            print(f"{cp.id}: {cp.create_time}{comment}")


def cmd_checkpoint_create(client: SpritesClient, sprite_name: str, args: List[str]) -> None:
    """Create checkpoint."""
    comment = args[0] if args else ""

    sprite = client.sprite(sprite_name)
    try:
        stream = sprite.create_checkpoint(comment)
        for msg in stream:
            print(json.dumps({"type": msg.type, "data": msg.data, "error": msg.error}))
    except Exception as e:
        print(f"Failed to create checkpoint: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_checkpoint_get(client: SpritesClient, sprite_name: str, args: List[str], as_json: bool) -> None:
    """Get checkpoint details."""
    if len(args) < 1:
        print("Error: checkpoint ID is required", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    cp = sprite.get_checkpoint(args[0])

    if as_json:
        print(json.dumps({
            "id": cp.id,
            "create_time": cp.create_time.isoformat(),
            "comment": cp.comment,
            "history": cp.history,
        }, indent=2))
    else:
        print(f"ID: {cp.id}")
        print(f"Created: {cp.create_time}")
        if cp.comment:
            print(f"Comment: {cp.comment}")
        if cp.history:
            print(f"History: {', '.join(cp.history)}")


def cmd_checkpoint_restore(client: SpritesClient, sprite_name: str, args: List[str]) -> None:
    """Restore a checkpoint."""
    if len(args) < 1:
        print("Error: checkpoint ID is required", file=sys.stderr)
        sys.exit(1)

    sprite = client.sprite(sprite_name)
    stream = sprite.restore_checkpoint(args[0])
    for msg in stream:
        print(json.dumps({"type": msg.type, "data": msg.data, "error": msg.error}))


def cmd_exec(
    client: SpritesClient,
    sprite_name: str,
    command: str,
    cmd_args: List[str],
    options: Dict[str, Any],
) -> None:
    """Execute a command on a sprite."""
    sprite = client.sprite(sprite_name)

    # Parse options
    timeout = parse_duration(options.get("timeout") or "0")
    env = parse_env(options.get("env") or "")
    cwd = options.get("dir")
    output_mode = options.get("output", "stdout")
    tty = options.get("tty", False)
    tty_rows = options.get("tty_rows", 24)
    tty_cols = options.get("tty_cols", 80)

    # Build command
    all_args = [command] + cmd_args
    cmd = sprite.command(*all_args, env=env or None, cwd=cwd, timeout=timeout)

    # Configure TTY
    if tty:
        cmd.set_tty(True)
        cmd.set_tty_size(tty_rows, tty_cols)

    try:
        if output_mode == "stdout":
            output = cmd.output()
            sys.stdout.buffer.write(output)
            sys.stdout.buffer.flush()
        elif output_mode == "combined":
            output = cmd.combined_output()
            sys.stdout.buffer.write(output)
            sys.stdout.buffer.flush()
        elif output_mode == "exit-code":
            cmd.run()
        else:
            # Default streaming mode
            cmd.stdout = sys.stdout.buffer
            cmd.stderr = sys.stderr.buffer
            cmd.stdin = sys.stdin.buffer
            cmd.run()
    except ExitError as e:
        exit_code = e.exit_code()
        # For stdout/combined modes, print any captured output
        if output_mode in ("stdout", "combined") and e.stdout:
            sys.stdout.buffer.write(e.stdout)
            sys.stdout.buffer.flush()
        # Write error info to stdout for test harness capture
        error_msg = f"ExitError: exit code {exit_code}"
        if e.stderr:
            error_msg += f", stderr: {e.stderr.decode('utf-8', errors='replace')}"
        print(error_msg)
        sys.exit(exit_code)
    except SpriteTimeoutError as e:
        # Write to stdout for test harness capture
        print(f"Command timed out: {e}")
        sys.exit(1)
    except Exception as e:
        # Write to stdout for test harness capture
        print(f"Command failed: {e}")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    options, args = parse_args(sys.argv)

    if len(args) == 0:
        print(__doc__)
        sys.exit(1)

    command = args[0]
    command_args = args[1:]

    client = get_client(options["base_url"])

    # Commands that don't need sprite
    if command == "create":
        cmd_create(client, command_args)
        return

    if command == "destroy":
        cmd_destroy(client, command_args)
        return

    if command == "list":
        cmd_list(client)
        return

    # Commands that need sprite
    sprite_name = options.get("sprite")
    workdir = options.get("dir")
    as_json = options.get("json", False)

    # Filesystem commands
    if command.startswith("fs-"):
        if not sprite_name:
            print(f"Error: -sprite is required for {command} command", file=sys.stderr)
            sys.exit(1)

        flags = parse_fs_flags(command_args)

        if command == "fs-read":
            cmd_fs_read(client, sprite_name, workdir, flags)
        elif command == "fs-write":
            cmd_fs_write(client, sprite_name, workdir, flags)
        elif command == "fs-list":
            cmd_fs_list(client, sprite_name, workdir, flags)
        elif command == "fs-stat":
            cmd_fs_stat(client, sprite_name, workdir, flags)
        elif command == "fs-mkdir":
            cmd_fs_mkdir(client, sprite_name, workdir, flags)
        elif command == "fs-rm":
            cmd_fs_rm(client, sprite_name, workdir, flags)
        elif command == "fs-rename":
            cmd_fs_rename(client, sprite_name, workdir, flags)
        elif command == "fs-copy":
            cmd_fs_copy(client, sprite_name, workdir, flags)
        elif command == "fs-chmod":
            cmd_fs_chmod(client, sprite_name, workdir, flags)
        else:
            print(f"Error: unknown fs command: {command}", file=sys.stderr)
            sys.exit(1)
        return

    # Policy commands
    if command == "policy":
        if not sprite_name:
            print("Error: -sprite is required for policy command", file=sys.stderr)
            sys.exit(1)

        if len(command_args) == 0:
            print("Error: policy subcommand required (get, set)", file=sys.stderr)
            sys.exit(1)

        subcommand = command_args[0]
        if subcommand == "get":
            cmd_policy_get(client, sprite_name)
        elif subcommand == "set":
            cmd_policy_set(client, sprite_name, command_args[1:])
        else:
            print(f"Error: unknown policy subcommand: {subcommand}", file=sys.stderr)
            sys.exit(1)
        return

    # Checkpoint commands
    if command == "checkpoint":
        if not sprite_name:
            print("Error: -sprite is required for checkpoint command", file=sys.stderr)
            sys.exit(1)

        if len(command_args) == 0:
            print("Error: checkpoint subcommand required (list, create, get, restore)", file=sys.stderr)
            sys.exit(1)

        subcommand = command_args[0]
        if subcommand == "list":
            # Output JSON by default to match Go test-cli behavior
            cmd_checkpoint_list(client, sprite_name, as_json=True)
        elif subcommand == "create":
            cmd_checkpoint_create(client, sprite_name, command_args[1:])
        elif subcommand == "get":
            cmd_checkpoint_get(client, sprite_name, command_args[1:], as_json=True)
        elif subcommand == "restore":
            cmd_checkpoint_restore(client, sprite_name, command_args[1:])
        else:
            print(f"Error: unknown checkpoint subcommand: {subcommand}", file=sys.stderr)
            sys.exit(1)
        return

    # Unknown command - treat as exec command (run on sprite)
    if not sprite_name:
        print(f"Error: -sprite is required for exec commands", file=sys.stderr)
        sys.exit(1)

    cmd_exec(client, sprite_name, command, command_args, options)


if __name__ == "__main__":
    main()
