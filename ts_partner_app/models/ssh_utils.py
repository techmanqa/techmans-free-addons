"""Thin SSH helper around paramiko.

paramiko is an *optional* dependency: storing and displaying a client's server
details works without it. Only the live actions -- test connection, fetch
resources, run command, restart -- need it. Install with ``pip install paramiko``
and restart Odoo to enable them.
"""
import io
import logging

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard
    import paramiko
except ImportError:  # pragma: no cover
    paramiko = None

# Keep every SSH call short: a blocked connect ties up an HTTP worker until it
# gives up, so the defaults here are deliberately aggressive.
DEFAULT_TIMEOUT = 10


def ssh_available():
    return paramiko is not None


def _require_paramiko():
    if paramiko is None:
        raise UserError(_(
            "SSH support requires the 'paramiko' Python package, which is not "
            "installed on this Odoo server.\n\n"
            "Install it with 'pip install paramiko' and restart Odoo to enable "
            "connection tests, resource checks and remote commands."
        ))


def _load_private_key(key_str, passphrase):
    """Try the common key types until one parses."""
    last_error = None
    for key_cls in (
        getattr(paramiko, 'Ed25519Key', None),
        getattr(paramiko, 'RSAKey', None),
        getattr(paramiko, 'ECDSAKey', None),
        getattr(paramiko, 'DSSKey', None),
    ):
        if key_cls is None:
            continue
        try:
            return key_cls.from_private_key(io.StringIO(key_str), password=passphrase or None)
        except paramiko.SSHException as err:  # wrong type or wrong passphrase
            last_error = err
    raise UserError(_(
        "Could not read the SSH private key (unsupported format or wrong "
        "passphrase): %s", last_error,
    ))


def run_command(command, *, host, port=22, username=None, auth_type='password',
                password=None, private_key=None, passphrase=None,
                timeout=DEFAULT_TIMEOUT):
    """Open an SSH connection, run ``command``, return the result.

    :returns: tuple ``(exit_status, stdout, stderr)`` -- strings decoded as
        UTF-8 with replacement.
    :raises UserError: on missing paramiko, missing credentials, or any
        connection/auth failure (message is safe to show to the user).
    """
    _require_paramiko()

    if not host:
        raise UserError(_("No server host is configured."))
    if not username:
        raise UserError(_("No SSH user is configured."))

    client = paramiko.SSHClient()
    # AutoAddPolicy: we do not pin host keys. Acceptable for an admin-only tool
    # against known infrastructure; revisit if this is ever exposed wider.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {
        'hostname': host,
        'port': port or 22,
        'username': username,
        'timeout': timeout,
        'banner_timeout': timeout,
        'auth_timeout': timeout,
        'allow_agent': False,
        'look_for_keys': False,
    }

    if auth_type == 'key':
        if not private_key:
            raise UserError(_("Key authentication is selected but no private key is stored."))
        connect_kwargs['pkey'] = _load_private_key(private_key, passphrase)
    else:
        if not password:
            raise UserError(_("Password authentication is selected but no password is stored."))
        connect_kwargs['password'] = password

    try:
        client.connect(**connect_kwargs)
    except UserError:
        raise
    except Exception as err:  # noqa: BLE001 - paramiko raises a wide range
        raise UserError(_(
            "SSH connection to %(host)s failed: %(err)s", host=host, err=err,
        ))

    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        exit_status = stdout.channel.recv_exit_status()
        return exit_status, out, err
    finally:
        client.close()
