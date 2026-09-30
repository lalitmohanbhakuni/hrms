# core/webauthn_views.py
"""
WebAuthn device verification endpoints for NitoHR
"""
import json
import logging
import traceback
from datetime import datetime

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.conf import settings

from webauthn import (
    generate_registration_options, verify_registration_response,
    generate_authentication_options, verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, UserVerificationRequirement,
    ResidentKeyRequirement, PublicKeyCredentialDescriptor,
    AuthenticatorTransport,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from core.models import EmployeeDevice, AttendanceDevicePolicy


# ═══════════════════════════════════════════════════════════
#  DEBUG LOGGER (file-based)
# ═══════════════════════════════════════════════════════════
_webauthn_logger = logging.getLogger('webauthn_debug')
_webauthn_logger.setLevel(logging.DEBUG)
_webauthn_logger.propagate = False  # Don't send to console (avoid duplication)

if not _webauthn_logger.handlers:
    try:
        _handler = logging.FileHandler('/tmp/webauthn_debug.log')
        _handler.setLevel(logging.DEBUG)
        _formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        _handler.setFormatter(_formatter)
        _webauthn_logger.addHandler(_handler)
    except Exception:
        # Fallback to NullHandler if file can't be created
        _webauthn_logger.addHandler(logging.NullHandler())

# ─── Config Helpers (lazy read from settings) ──────────────

def _get_rp_id():
    return getattr(settings, 'WEBAUTHN_RP_ID', 'localhost')


def _get_rp_name():
    return getattr(settings, 'WEBAUTHN_RP_NAME', 'NitoHR')


def _get_origin():
    return getattr(settings, 'WEBAUTHN_ORIGIN', 'http://localhost:8000')


# ─── Shared Helpers ────────────────────────────────────────

def _get_policy(user):
    profile = getattr(user, 'profile', None)
    if not profile:
        return None
    return AttendanceDevicePolicy.objects.filter(company=profile.company).first()


def _device_type_from_request(request):
    try:
        data = json.loads(request.body) if request.body else {}
    except (ValueError, json.JSONDecodeError):
        data = {}
    dt = data.get('device_type', 'mobile')
    return dt if dt in ('mobile', 'laptop') else 'mobile'


def _error(msg, code=None, status=400):
    payload = {'success': False, 'error': msg}
    if code:
        payload['code'] = code
    return JsonResponse(payload, status=status)


# ─── 1. CHECK (session verification status) ────────────────

@login_required
def webauthn_check(request):
    """
    Check if device verification is required and already done in this session.
    Frontend calls this before clock_in / clock_out.
    """
    if request.method != 'POST':
        return _error('POST required', status=405)

    policy = _get_policy(request.user)

    # Policy disabled → skip device check
    if not policy or not policy.enabled:
        return JsonResponse({'success': True, 'verified': True, 'required': False})

    device_verified = request.session.get('device_verified', False)
    verified_at_str = request.session.get('device_verified_at')
    verified_device_id = request.session.get('verified_device_id')

    is_recent = False
    if verified_at_str:
        try:
            verified_time = datetime.fromisoformat(verified_at_str)
            if timezone.is_naive(verified_time):
                verified_time = timezone.make_aware(verified_time)
            delta = (timezone.now() - verified_time).total_seconds()
            is_recent = delta < 300  # 5 minutes
        except (ValueError, TypeError):
            is_recent = False

    # ⬇️ CHANGE #1: registration_status='approved' add kiya
    if device_verified and is_recent and verified_device_id:
        exists = EmployeeDevice.objects.filter(
            id=verified_device_id,
            user=request.user,
            is_active=True,
            registration_status='approved',
        ).exists()
        if exists:
            return JsonResponse({'success': True, 'verified': True, 'required': True})

    # Not verified → tell frontend what to do
    device_type = _device_type_from_request(request)

    # ⬇️ CHANGE #2: Naya block (pending/rejected/approved check)
    all_devices = EmployeeDevice.objects.filter(
        user=request.user,
        device_type=device_type,
        is_active=True,
    )

    approved_devices = all_devices.filter(registration_status='approved')
    pending_devices = all_devices.filter(registration_status='pending')
    rejected_devices = all_devices.filter(registration_status='rejected')

    # Approved device exists → ask for verification
    if approved_devices.exists():
        return JsonResponse({
            'success': False,
            'verified': False,
            'required': True,
            'code': 'DEVICE_VERIFICATION_REQUIRED',
            'error': 'Please verify this device.'
        })

    # Pending HR approval
    if pending_devices.exists():
        return JsonResponse({
            'success': False,
            'verified': False,
            'required': True,
            'code': 'PENDING_HR_APPROVAL',
            'error': 'Your device is waiting for HR approval.'
        })

    # Rejected
    if rejected_devices.exists():
        device = rejected_devices.first()
        return JsonResponse({
            'success': False,
            'verified': False,
            'required': True,
            'code': 'DEVICE_REJECTED',
            'error': f'Your device registration was rejected. {device.rejection_reason or "Contact HR."}'
        })

    # No devices → register new
    return JsonResponse({
        'success': False,
        'verified': False,
        'required': True,
        'code': 'DEVICE_REGISTRATION_REQUIRED',
        'error': 'No device registered. Please register this device first.'
    })



# ─── 2. REGISTER — BEGIN ───────────────────────────────────

@login_required
def webauthn_register_begin(request):
    """Generate WebAuthn registration options (first-time device)."""
    if request.method != 'POST':
        return _error('POST required', status=405)

    policy = _get_policy(request.user)
    if not policy or not policy.enabled:
        return _error('Device verification is disabled')

    device_type = _device_type_from_request(request)

    max_allowed = (
        policy.max_mobile_devices if device_type == 'mobile'
        else policy.max_laptop_devices
    )

    # ⬇️ NEW: Check if this device type is completely disabled
    if max_allowed == 0:
        if device_type == 'laptop':
            return _error(
                'Laptop check-in is not allowed. '
                'Please use your mobile device to clock in/out.',
                code='LAPTOP_NOT_ALLOWED'
            )
        elif device_type == 'mobile':
            return _error(
                'Mobile check-in is not allowed. '
                'Please contact HR.',
                code='MOBILE_NOT_ALLOWED'
            )

    existing_count = EmployeeDevice.objects.filter(
        user=request.user,
        device_type=device_type,
        is_active=True
    ).count()

    if existing_count >= max_allowed:
        return _error(
            f"Maximum {max_allowed} {device_type} device(s) allowed. "
            f"Please contact HR to reset.",
            code='MAX_DEVICES_REACHED'
        )

    # Exclude already-registered credentials (prevent duplicate)
    existing_credentials = EmployeeDevice.objects.filter(
        user=request.user,
        is_active=True
    ).values_list('credential_id', flat=True)

    profile = request.user.profile
    user_id_bytes = str(request.user.id).encode()

    options = generate_registration_options(
        rp_id=_get_rp_id(),
        rp_name=_get_rp_name(),
        user_id=user_id_bytes,
        user_name=request.user.username,
        user_display_name=(
            getattr(profile, 'full_name', None)
            or request.user.get_full_name()
            or request.user.username
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(cid))
            for cid in existing_credentials if cid
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
    )

    request.session['webauthn_register_challenge'] = bytes_to_base64url(options.challenge)
    request.session['webauthn_register_device_type'] = device_type

    return JsonResponse(json.loads(options_to_json(options)))

# ─── 3. REGISTER — COMPLETE ────────────────────────────────


@login_required
def webauthn_register_complete(request):
    """Verify and save new device credential."""
    # ⬇️ YEH ADD KAREIN (function entry logging)
    _webauthn_logger.error("=" * 70)
    _webauthn_logger.error("REGISTER COMPLETE ENTERED")
    _webauthn_logger.error(f"Method: {request.method}")
    _webauthn_logger.error(f"User: {getattr(request.user, 'username', 'NO USER')}")
    _webauthn_logger.error(f"Session keys: {list(request.session.keys())}")
    _webauthn_logger.error(f"Challenge in session: {'webauthn_register_challenge' in request.session}")
    _webauthn_logger.error("=" * 70)

    if request.method != 'POST':
        return _error('POST required', status=405)

    challenge_b64 = request.session.pop('webauthn_register_challenge', None)
    device_type = request.session.pop('webauthn_register_device_type', 'mobile')

    # ⬇️ YEH ADD KAREIN (challenge logging)
    _webauthn_logger.error(f"challenge_b64: {challenge_b64[:30] if challenge_b64 else 'NONE'}")
    _webauthn_logger.error(f"device_type: {device_type}")

    if not challenge_b64:
        _webauthn_logger.error("CHALLENGE MISSING - returning 400")
        return _error('Challenge expired. Please retry.')

    try:
        challenge = base64url_to_bytes(challenge_b64)
        attestation = json.loads(request.body)
    except (ValueError, json.JSONDecodeError):
        return _error('Invalid request data.')

    try:
        verification = verify_registration_response(
            credential=attestation,
            expected_challenge=challenge,
            expected_origin=_get_origin(),
            expected_rp_id=_get_rp_id(),
        )
    except Exception as e:
        _webauthn_logger.error("=" * 70)
        _webauthn_logger.error(f"REGISTRATION FAILED: {type(e).__name__}: {e}")
        _webauthn_logger.error(f"Expected Origin: {_get_origin()}")
        _webauthn_logger.error(f"Expected RP_ID: {_get_rp_id()}")
        _webauthn_logger.error(f"Challenge (first 30): {challenge[:30] if challenge else 'None'}")
        _webauthn_logger.error(f"Attestation ID: {attestation.get('id', 'N/A')[:40]}")
        _webauthn_logger.error(f"Attestation Type: {attestation.get('type', 'N/A')}")
        _webauthn_logger.error("Full traceback:")
        _webauthn_logger.error(traceback.format_exc())
        _webauthn_logger.error("=" * 70)
        return _error(f'Registration failed: {str(e)}')

    policy = _get_policy(request.user)
    if not policy or not policy.enabled:
        return _error('Device verification is disabled')

    device_name = request.META.get('HTTP_USER_AGENT', '')[:150]

    # Capture IP
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    client_ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')

    # Check if HR approval required
    requires_approval = policy.require_hr_approval

    try:
        device = EmployeeDevice.objects.create(
            user=request.user,
            company=request.user.profile.company,
            device_type=device_type,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            device_name=device_name,
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            ip_address=client_ip,
            is_primary=not EmployeeDevice.objects.filter(
                user=request.user,
                device_type=device_type,
                is_active=True
            ).exists(),
            registration_status='pending' if requires_approval else 'approved',
        )
    except Exception as e:
        return _error(f'Could not save device: {str(e)}')

    # Set approved_at if auto-approved
    if not requires_approval:
        device.approved_at = timezone.now()
        device.save(update_fields=['approved_at'])

    # Notify HR
    if policy.notify_hr_on_new_device:
        try:
            from core.utils import create_notification
            create_notification(
                company=request.user.profile.company,
                message=(
                    f"New {device_type} device registered for "
                    f"{request.user.username}"
                    + (" (pending HR approval)" if requires_approval else "")
                ),
                notification_type='action',
            )
        except Exception:
            pass

    # ALAG RESPONSE — pending vs approved
    if requires_approval:
        return JsonResponse({
            'success': False,
            'device_id': device.id,
            'code': 'PENDING_HR_APPROVAL',
            'message': 'Device registered. Waiting for HR approval.'
        })
    else:
        request.session['device_verified'] = True
        request.session['device_verified_at'] = timezone.now().isoformat()
        request.session['verified_device_id'] = device.id

        return JsonResponse({
            'success': True,
            'device_id': device.id,
            'message': 'Device registered successfully'
        })
        


# ─── 4. AUTHENTICATE — BEGIN ───────────────────────────────

@login_required
def webauthn_authenticate_begin(request):
    """Generate WebAuthn authentication options for existing device."""
    if request.method != 'POST':
        return _error('POST required', status=405)

    policy = _get_policy(request.user)
    if not policy or not policy.enabled:
        return _error('Device verification is disabled')

    device_type = _device_type_from_request(request)

    devices = EmployeeDevice.objects.filter(
        user=request.user,
        device_type=device_type,
        is_active=True
    )

    if not devices.exists():
        return _error(
            'No registered device found',
            code='DEVICE_REGISTRATION_REQUIRED'
        )

    allow_creds = []
    for d in devices:
        allow_creds.append(
            PublicKeyCredentialDescriptor(
                id=bytes(d.credential_id),
                # transports skip — browser sab options dikhayega
            )
        )

    options = generate_authentication_options(
        rp_id=_get_rp_id(),
        allow_credentials=allow_creds,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    request.session['webauthn_auth_challenge'] = bytes_to_base64url(options.challenge)
    request.session['webauthn_auth_device_type'] = device_type

    return JsonResponse(json.loads(options_to_json(options)))


# ─── 5. AUTHENTICATE — COMPLETE ────────────────────────────

@login_required
def webauthn_authenticate_complete(request):
    """Verify device signature."""
    if request.method != 'POST':
        return _error('POST required', status=405)

    challenge_b64 = request.session.pop('webauthn_auth_challenge', None)
    if not challenge_b64:
        return _error('Challenge expired. Please retry.')

    try:
        challenge = base64url_to_bytes(challenge_b64)
        assertion = json.loads(request.body)
    except (ValueError, json.JSONDecodeError):
        return _error('Invalid request data.')

    try:
        raw_id = assertion.get('rawId') or assertion.get('id')
        credential_id_bytes = base64url_to_bytes(raw_id)
    except Exception:
        return _error('Invalid credential ID.')

    device = EmployeeDevice.objects.filter(
        credential_id=credential_id_bytes,
        user=request.user,
        is_active=True
    ).first()

    if not device:
        return _error('This device is not registered for your account.')

    try:
        verification = verify_authentication_response(
            credential=assertion,
            expected_challenge=challenge,
            expected_origin=_get_origin(),
            expected_rp_id=_get_rp_id(),
            credential_public_key=bytes(device.public_key),
            credential_current_sign_count=device.sign_count,
        )
    except Exception as e:
        return _error(f'Verification failed: {str(e)}')

    # Update sign count (replay protection)
    device.sign_count = verification.new_sign_count
    device.last_used_at = timezone.now()
    device.save(update_fields=['sign_count', 'last_used_at'])

    request.session['device_verified'] = True
    request.session['device_verified_at'] = timezone.now().isoformat()
    request.session['verified_device_id'] = device.id

    return JsonResponse({
        'success': True,
        'device_id': device.id,
        'message': 'Device verified'
    })