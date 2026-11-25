"""Machine-wide DPAPI credential storage and per-account Credential Manager fallback."""
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
from uuid import uuid4

logger = logging.getLogger(__name__)

DUMMY_IDS = {
    'a0000000-0000-4000-8000-000000000011',
    'c0000000-0000-4000-8000-000000000021',
    '275f7586-a64c-4b95-aed2-0ec853ba724c',
}


def machine_credential_path():
    return Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'EFL_NEXUS_Monitoring' / 'credential.enc'


def user_monitoring_dir():
    override = os.environ.get('EFL_USER_MONITORING_DIR')
    if override:
        return Path(override)
    return Path(os.environ.get('LOCALAPPDATA', '')) / 'EFL_NEXUS' / 'Monitoring'


def user_credential_path():
    return user_monitoring_dir() / 'credential.enc'


def activation_token_path():
    return Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'EFL_NEXUS_Monitoring' / 'monitoring_active.token'


def user_activation_token_path():
    return user_monitoring_dir() / 'monitoring_active.token'


def set_machine_active(active=True, path=None):
    """Enable or disable machine-specific monitoring activation token."""
    if path:
        targets = [Path(path)]
    else:
        targets = [activation_token_path(), user_activation_token_path()]

    for target in targets:
        if active:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('ACTIVE', encoding='utf-8')
            except (PermissionError, OSError):
                pass
        else:
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass


def is_machine_active(path=None):
    """Check if this host has the local machine-specific activation token."""
    if path:
        return Path(path).is_file()
    if activation_token_path().is_file():
        return True
    return user_activation_token_path().is_file()


def save_machine_credential(record, path=None):
    """Encrypt and store machine credential using DPAPI CRYPTPROTECT_LOCAL_MACHINE."""
    import win32crypt
    payload = json.dumps(record).encode('utf-8')
    # Flag 4 = CRYPTPROTECT_LOCAL_MACHINE: any user process on this specific Windows host can decrypt
    encrypted = win32crypt.CryptProtectData(payload, 'EFL_NEXUS Device Credential', None, None, None, 4)

    if path:
        targets = [Path(path)]
    else:
        targets = [machine_credential_path(), user_credential_path()]

    saved = False
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = target.with_name(f'{target.stem}_{uuid4().hex}.tmp')
            with tmp_path.open('wb') as f:
                f.write(encrypted)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
            saved = True

            # Apply hardened ACLs if provisioning to production ProgramData
            programdata_root = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')).resolve()
            if target.resolve().is_relative_to(programdata_root):
                try:
                    import win32security
                    administrators = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid, None)
                    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                        'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;BU)', 1)
                    win32security.SetNamedSecurityInfo(
                        str(target), win32security.SE_FILE_OBJECT,
                        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                        administrators, None, descriptor.GetSecurityDescriptorDacl(), None
                    )
                except Exception as e:
                    logger.debug('ACL application deferred (%s)', e)
        except (PermissionError, OSError) as e:
            logger.debug('Could not write credential to %s: %s', target, e)

    if not saved and not path:
        raise PermissionError('Could not save machine credential to either user or machine path.')


def load_machine_credential(path=None):
    """Read and decrypt machine credential using DPAPI. Return None if not found or dummy."""
    import win32crypt
    if path:
        candidates = [Path(path)]
    else:
        candidates = [machine_credential_path(), user_credential_path()]

    for target in candidates:
        if not target.exists():
            continue
        try:
            encrypted = target.read_bytes()
            _, decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
            data = json.loads(decrypted.decode('utf-8'))
            cred_id = data.get('credential_id')
            inst_uuid = data.get('installation_uuid')
            dev_id = data.get('device_id')
            if cred_id in DUMMY_IDS or inst_uuid in DUMMY_IDS or dev_id in DUMMY_IDS:
                logger.debug('Ignoring mock/dummy credential found at %s', target)
                continue
            return data
        except Exception as e:
            logger.debug('Failed to decrypt credential from %s: %s', target, e)
            continue
    return None


def delete_machine_credential(path=None):
    """Remove machine credential."""
    if path:
        targets = [Path(path)]
    else:
        targets = [user_credential_path(), machine_credential_path()]
    for target in targets:
        if target.exists():
            try:
                target.unlink()
            except OSError:
                pass


def target(url, credential_id):
    return 'EFL_NEXUS:cloud-v2:' + hashlib.sha256((url + '/' + credential_id).encode()).hexdigest()


def save(url, record):
    import win32cred
    win32cred.CredWrite({'Type': win32cred.CRED_TYPE_GENERIC,
        'TargetName': target(url, record['credential_id']), 'UserName': record['credential_id'],
        'CredentialBlob': json.dumps(record),
        'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)


def load(url, credential_id):
    import win32cred
    blob = win32cred.CredRead(target(url, credential_id), win32cred.CRED_TYPE_GENERIC)['CredentialBlob']
    if isinstance(blob, bytes):
        try:
            return json.loads(blob.decode('utf-16-le'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return json.loads(blob.decode('utf-8'))
    return json.loads(blob)


def delete(url, credential_id):
    """Remove only the explicitly selected account credential."""
    import win32cred
    win32cred.CredDelete(target(url, credential_id), win32cred.CRED_TYPE_GENERIC, 0)


def pending(enrollment):
    return {**enrollment, 'credential_id': str(uuid4()), 'secret': secrets.token_hex(32)}
