"""Machine identity is provisioned independently of application release folders."""
import json
import logging
import os
from pathlib import Path
import secrets
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

DUMMY_IDS = {
    'a0000000-0000-4000-8000-000000000011',
    'c0000000-0000-4000-8000-000000000021',
    '275f7586-a64c-4b95-aed2-0ec853ba724c',
}


DEFAULT_SUPABASE_URL = os.environ.get('EFL_NEXUS_SUPABASE_URL', 'https://wykmgymitdxkqbpywpzh.supabase.co')
DEFAULT_SUPABASE_KEY = os.environ.get('EFL_NEXUS_SUPABASE_KEY', 'sb_publishable_4kmXj_vznXL8qyK5hFXeoQ_eSGi3xkR')


def identity_path():
    return Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'EFL_NEXUS_Monitoring' / 'installation.json'


def user_identity_path():
    override = os.environ.get('EFL_USER_MONITORING_DIR')
    if override:
        return Path(override) / 'installation.json'
    return Path(os.environ.get('LOCALAPPDATA', '')) / 'EFL_NEXUS' / 'Monitoring' / 'installation.json'


def credential_path():
    return Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'EFL_NEXUS_Monitoring' / 'credential.enc'


def machine_binding():
    # Local anti-clone binding, never transmitted. A copied app folder has no identity.
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                        0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        return str(winreg.QueryValueEx(key, 'MachineGuid')[0])


def read_identity(path=None):
    if path:
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f'Identity file not found at {target}')
        data = json.loads(target.read_text(encoding='utf-8'))
        if data.get('machine_binding') != machine_binding():
            raise ValueError('Shared identity belongs to another Windows installation. Run setup again.')
        uuid_val = str(UUID(data['installation_uuid']))
        if uuid_val in DUMMY_IDS:
            raise FileNotFoundError('Identity file contains dummy UUID')
        return uuid_val

    # Check primary identity_path first, then fallback to user_identity_path
    targets = [identity_path(), user_identity_path()]
    for target in targets:
        if not target.exists():
            continue
        try:
            data = json.loads(target.read_text(encoding='utf-8'))
            if data.get('machine_binding') != machine_binding():
                continue
            uuid_val = str(UUID(data['installation_uuid']))
            if uuid_val in DUMMY_IDS:
                logger.debug('Ignoring mock/dummy installation UUID at %s', target)
                continue
            return uuid_val
        except Exception:
            continue
    raise FileNotFoundError('Valid identity file not found')


def get_or_create_identity(path=None):
    """Retrieve existing installation UUID or generate and persist a new one bound to MachineGuid."""
    try:
        return read_identity(path)
    except Exception:
        pass

    value = str(uuid4())
    record = {'installation_uuid': value, 'machine_binding': machine_binding()}

    targets = [Path(path)] if path else [identity_path(), user_identity_path()]
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(record), encoding='utf-8')
            return value
        except (PermissionError, OSError) as e:
            logger.debug('Could not write identity to %s: %s', target, e)

    return value


def auto_register_machine(url=None, key=None, force=False):
    """Zero-touch device self-registration against Supabase backend.
    Enrolls this computer without requiring manual dashboard code generation,
    while respecting revocation status.
    """
    import socket
    from .cloud_client import CloudClient, CloudError
    from .security import save_machine_credential, load_machine_credential, set_machine_active

    if not force:
        existing = load_machine_credential()
        if existing and existing.get('credential_id') and existing.get('credential_id') not in DUMMY_IDS:
            set_machine_active(True)
            return True

    target_url = url or DEFAULT_SUPABASE_URL
    target_key = key or DEFAULT_SUPABASE_KEY

    try:
        inst_id = get_or_create_identity()
    except Exception as e:
        logger.warning('Cannot determine machine identity for auto-registration: %s', e)
        return False

    cred_id = str(uuid4())
    cred_secret = secrets.token_hex(32)
    device_name = socket.gethostname()[:120]

    client = CloudClient(target_url, target_key)
    try:
        enroll_result = client.post('device-enroll', {
            'auto_register': True,
            'device_name': device_name,
            'installation_uuid': inst_id,
            'credential_id': cred_id,
            'secret': cred_secret
        })
        machine_record = {
            'url': client.url,
            'key': client.key,
            'device_id': enroll_result.get('device_id'),
            'credential_id': cred_id,
            'secret': cred_secret,
            'installation_uuid': inst_id
        }
        save_machine_credential(machine_record)
        set_machine_active(True)
        logger.info('Device auto-registered successfully: %s (%s)', device_name, enroll_result.get('device_id'))
        return True
    except CloudError as e:
        if e.status == 403:
            logger.warning('Device auto-registration rejected: device has been revoked.')
            from .decommission import trigger_self_destruct
            trigger_self_destruct(reason='Device auto-registration rejected (revoked)')
        else:
            logger.warning('Device auto-registration cloud error (status %s)', e.status)
        return False
    except Exception as e:
        logger.warning('Device auto-registration failed: %s', e)
        return False
    finally:
        client.close()


def provision(provisioning_source=None):
    """Run only from elevated setup/admin process; never from standard operator launch."""
    import ctypes
    import win32security as security
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise PermissionError('Shared device setup requires Windows administrator approval.')
    path = identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    is_junction = getattr(path.parent, 'is_junction', lambda: False)()
    if path.parent.is_symlink() or is_junction:
        raise ValueError('Shared identity directory must not be a link.')

    descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;BU)', 1)
    administrators = security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid, None)
    programdata_root = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')).resolve()

    def _apply_acls(target_path):
        try:
            target_resolved = Path(target_path).resolve()
            # Only apply restrictive system ACLs when provisioning to real ProgramData location
            if target_resolved.is_relative_to(programdata_root):
                security.SetNamedSecurityInfo(str(target_path), security.SE_FILE_OBJECT,
                    security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
                    administrators, None, descriptor.GetSecurityDescriptorDacl(), None)
        except Exception:
            try:
                target_resolved = Path(target_path).resolve()
                if target_resolved.is_relative_to(programdata_root):
                    security.SetNamedSecurityInfo(str(target_path), security.SE_FILE_OBJECT,
                        security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
                        None, None, descriptor.GetSecurityDescriptorDacl(), None)
            except Exception:
                pass

    _apply_acls(path.parent)

    import win32event
    import win32api
    mutex = win32event.CreateMutex(None, False, 'Global\\EFL_NEXUS_Monitoring_Setup')
    acquired = win32event.WaitForSingleObject(mutex, 5000)
    if acquired not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
        win32api.CloseHandle(mutex)
        raise TimeoutError('Another shared device setup is in progress.')
    temporary = path.with_name(str(uuid4()) + '.tmp')
    try:
        is_target_junction = getattr(path, 'is_junction', lambda: False)()
        if path.is_symlink() or is_target_junction:
            raise ValueError('Identity file must not be a link.')
        inst_id = None
        if path.exists():
            _apply_acls(path)
            try:
                inst_id = read_identity(path)
            except Exception:
                inst_id = None
        if not inst_id:
            value = str(uuid4())
            with temporary.open('w', encoding='utf-8') as output:
                json.dump({'installation_uuid': value, 'machine_binding': machine_binding()}, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            _apply_acls(path)
            inst_id = value
            # Wipe any stale mock credential in ProgramData
            p_cred = path.parent / 'credential.enc'
            if p_cred.exists():
                try:
                    p_cred.unlink()
                except OSError:
                    pass

        # Handle optional device enrollment during elevated provisioning
        data = None
        source_file = None
        if isinstance(provisioning_source, dict):
            data = provisioning_source
        elif isinstance(provisioning_source, (str, Path)):
            src_path = Path(provisioning_source)
            if src_path.is_file():
                data = json.loads(src_path.read_text(encoding='utf-8'))
                source_file = src_path
            else:
                try:
                    data = json.loads(str(provisioning_source))
                except Exception:
                    data = None
        elif provisioning_source is None:
            auto_path = path.parent / 'provisioning.json'
            if auto_path.is_file():
                data = json.loads(auto_path.read_text(encoding='utf-8'))
                source_file = auto_path

        if data:
            required = {'url', 'key', 'enrollment_id', 'code', 'installation_uuid'}
            if not required.issubset(set(data)):
                raise ValueError(f'Invalid provisioning data, missing: {required - set(data)}')
            if str(UUID(data['installation_uuid'])) != inst_id:
                raise ValueError('Provisioning payload installation UUID does not match this machine')
            if len(data['code']) != 64 or any(c not in '0123456789abcdef' for c in data['code'].lower()):
                raise ValueError('Invalid enrollment code format')

            from .cloud_client import CloudClient
            from .security import save_machine_credential

            cred_id = str(uuid4())
            cred_secret = secrets.token_hex(32)
            client = CloudClient(data['url'], data['key'])
            try:
                enroll_result = client.post('device-enroll', {
                    'enrollment_id': data['enrollment_id'],
                    'code': data['code'],
                    'installation_uuid': inst_id,
                    'credential_id': cred_id,
                    'secret': cred_secret
                })
                machine_record = {
                    'url': client.url,
                    'key': client.key,
                    'device_id': enroll_result.get('device_id'),
                    'credential_id': cred_id,
                    'secret': cred_secret,
                    'installation_uuid': inst_id
                }
                save_machine_credential(machine_record)
                from .security import set_machine_active
                set_machine_active(True, path=path.parent / 'monitoring_active.token')
                logger.info('Machine monitoring credential provisioned successfully.')
            finally:
                client.close()

            if source_file and source_file.exists():
                try:
                    # Securely overwrite and unlink temporary provisioning file
                    with source_file.open('r+b') as sf:
                        length = sf.seek(0, os.SEEK_END)
                        sf.seek(0)
                        sf.write(b'\x00' * length)
                        sf.flush()
                        os.fsync(sf.fileno())
                    source_file.unlink()
                except OSError:
                    pass

            return inst_id, cred_id

        # If no explicit provisioning payload is provided, attempt zero-touch auto-registration
        auto_ok = auto_register_machine()
        if auto_ok:
            from .security import load_machine_credential
            cred = load_machine_credential(path.parent / 'credential.enc')
            if cred and cred.get('credential_id'):
                return inst_id, cred['credential_id']

        return inst_id
    finally:
        if temporary.exists():
            temporary.unlink()
        win32event.ReleaseMutex(mutex)
        win32api.CloseHandle(mutex)
