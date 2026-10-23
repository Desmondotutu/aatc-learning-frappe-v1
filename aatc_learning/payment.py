import frappe
from frappe import _


def process_training_payment(enrollment_name, gateway='Mock', amount=0, currency='XAF'):
    """
    Process payment for training enrollment.

    For Mock gateway: simulates payment success based on configured rate.
    For real gateways: would integrate with Stripe/PayPal APIs.

    On successful payment:
    - Sets LMS Enrollment.payment_status = 'Paid'
    - Creates Payment Record if Payments app is available
    """
    enrollment = frappe.get_doc('LMS Enrollment', enrollment_name)

    # Check payment status field exists
    if not hasattr(enrollment, 'payment_status'):
        # Create custom field if it doesn't exist
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
        create_custom_fields({
            "LMS Enrollment": [{
                "fieldname": "payment_status",
                "label": "Payment Status",
                "fieldtype": "Select",
                "options": "Unpaid\nPaid\nRefunded\nFailed",
                "default": "Unpaid",
                "insert_after": "examiner_decision",
            }]
        })
        enrollment.reload()

    if enrollment.payment_status == 'Paid':
        frappe.throw(_('Enrollment is already paid'))

    settings = frappe.get_single('AATC Settings')
    payment_enabled = settings.get('payment_enabled', 0)
    configured_gateway = settings.get('payment_gateway', 'Mock')

    if not payment_enabled:
        frappe.throw(_('Payments are not enabled in AATC Settings'))

    # Use configured gateway unless explicitly overridden
    actual_gateway = gateway if gateway != 'Mock' else configured_gateway

    success = False

    if actual_gateway == 'Mock':
        # Mock payment: always succeeds for testing (or based on success rate)
        import random
        success_rate = settings.get('payment_mock_success_rate', 100)
        success = random.randint(1, 100) <= success_rate

        if success:
            enrollment.payment_status = 'Paid'
            enrollment.save(ignore_permissions=True)
            frappe.db.commit()

            frappe.log_error(
                title='Mock Payment Success',
                message=f'Mock payment succeeded for enrollment {enrollment_name}'
            )
        else:
            enrollment.payment_status = 'Failed'
            enrollment.save(ignore_permissions=True)
            frappe.db.commit()

            frappe.log_error(
                title='Mock Payment Failure',
                message=f'Mock payment failed for enrollment {enrollment_name} (simulated)'
            )
            frappe.throw(_('Mock payment failed. Please try again or contact support.'))

    elif actual_gateway == 'Stripe':
        # Stripe integration placeholder
        frappe.throw(_('Stripe integration not yet implemented'))

    elif actual_gateway == 'PayPal':
        # PayPal integration placeholder
        frappe.throw(_('PayPal integration not yet implemented'))

    else:
        frappe.throw(_(f'Unknown payment gateway: {actual_gateway}'))

    return {
        'status': 'success' if success else 'failed',
        'enrollment': enrollment_name,
        'gateway': actual_gateway,
        'amount': amount,
        'currency': currency
    }