# AATC Learning - Phase 5E end-to-end acceptance tests

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, now_datetime
from frappe.utils.password import update_password

from aatc.certificate_automation import create_certificates_from_exam_session
from aatc_learning.payment import process_training_payment


MONDAY_URL = "https://api.monday.com/v2"


def _ok_response():
	response = MagicMock(status_code=200, text=json.dumps({"data": {"create_item": {"id": "1"}}}))
	response.raise_for_status.return_value = None
	return response


def _patch_monday(**kwargs):
	"""Mock requests.post so the outbound payload is built for real and only the send is stubbed."""
	return patch("requests.post", **{"return_value": _ok_response(), **kwargs})


def _posts(mock_post):
	"""Calls made to requests.post (the doc_event handlers' send path)."""
	posts = []
	for call in mock_post.call_args_list:
		url = call.args[0] if call.args else call.kwargs.get("url")
		if url == MONDAY_URL:
			posts.append(call)
	return posts


def _post_payload(call):
	return json.loads(call.kwargs["data"])


def _set_monday_settings(token, certificate_board, session_board, capa_board):
	settings = frappe.get_single("AATC Settings")
	settings.monday_api_token = token
	settings.monday_certificate_board_id = certificate_board
	settings.monday_session_board_id = session_board
	settings.monday_capa_board_id = capa_board
	settings.save(ignore_permissions=True)
	frappe.db.commit()


@contextmanager

def _as(user):
	"""Run the body as `user`: exercises the real workflow/role checks without new users."""
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous)


class TestMondayAcceptance(IntegrationTestCase):
	"""5E.1-5E.3: the three Monday.com pushes, end to end, with HTTP mocked."""

	def setUp(self):
		_set_monday_settings("e2e-monday-token", "board_cert", "board_session", "board_capa")

	def tearDown(self):
		_set_monday_settings("", "", "", "")

	def test_certificate_issuance_pushes_to_monday(self):
		# The certificate push is a doc event (on_update_after_submit), not a Webhook record.
		cert = _certificate_pending_qm()

		with _patch_monday() as mock_post:
			cert.reload()
			cert = apply_workflow(cert, "QM Approve")
			cert = apply_workflow(cert, "Submit HOT")
			cert = apply_workflow(cert, "HOT Approve")
			frappe.db.commit()

		self.assertEqual(cert.reload().status, "Approved")
		self.assertTrue(cert.hot_approved_at, "HOT approval did not stamp hot_approved_at")
		calls = _posts(mock_post)
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0].kwargs["headers"]["Authorization"], "e2e-monday-token")

		payload = _post_payload(calls[0])
		self.assertIn("create_item", payload["query"])
		variables = payload["variables"]
		self.assertEqual(variables["board_id"], "board_cert")
		self.assertEqual(
			variables["item_name"], f"Certificate {cert.certificate_number} - {cert.member_name}"
		)
		self.assertTrue(cert.reload().monday_push_sent, "monday_push_sent was not set by the handler")
		columns = variables["column_values"]
		self.assertEqual(columns["certificate_number"], cert.certificate_number)
		self.assertEqual(columns["member"], cert.member_name)
		self.assertEqual(columns["course"], cert.course_title)
		self.assertEqual(columns["status"], "Approved")

	def test_certificate_push_is_sent_once(self):
		"""Later transitions (Distribute) on an already-pushed certificate do not push again."""
		cert = _certificate_pending_qm()

		with _patch_monday() as mock_post:
			cert.reload()
			cert = apply_workflow(cert, "QM Approve")
			cert = apply_workflow(cert, "Submit HOT")
			cert = apply_workflow(cert, "HOT Approve")
			frappe.db.commit()
			self.assertEqual(len(_posts(mock_post)), 1)

			# Any further save that reaches on_update_after_submit must be a no-op.
			cert.reload()
			cert.hot_approved_by = cert.hot_approved_by or frappe.session.user
			cert.save(ignore_permissions=True)
			frappe.db.commit()

		self.assertEqual(len(_posts(mock_post)), 1, "certificate was pushed to Monday twice")
		self.assertTrue(cert.reload().monday_push_sent)

	def test_certificate_push_skipped_when_token_empty(self):
		"""No token: nothing is sent, monday_push_sent stays clear, and the approval stands."""
		_set_monday_settings("", "board_cert", "board_session", "board_capa")
		cert = _certificate_pending_qm()

		with _patch_monday() as mock_post:
			cert.reload()
			cert = apply_workflow(cert, "QM Approve")
			cert = apply_workflow(cert, "Submit HOT")
			cert = apply_workflow(cert, "HOT Approve")
			frappe.db.commit()

		self.assertEqual(cert.reload().status, "Approved")
		self.assertEqual(_posts(mock_post), [])
		self.assertFalse(cert.monday_push_sent, "a skipped push must leave the flag clear for a later retry")
		self.assertTrue(
			frappe.get_all(
				"Error Log",
				filters={"method": "Certificate not pushed to Monday", "reference_name": cert.name},
				pluck="name",
			)
		)

	def test_certificate_push_retries_on_failure(self):
		"""A failed send leaves the flag clear, so a subsequent save retries."""
		cert = _certificate_pending_qm()
		error_response = MagicMock()
		error_response.status_code = 500
		error_response.text = '{"error": "board unavailable"}'
		error_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error", response=error_response)

		success_response = MagicMock()
		success_response.status_code = 200
		success_response.text = json.dumps({"data": {"create_item": {"id": "1"}}})
		success_response.raise_for_status.return_value = None

		with patch("requests.post", side_effect=[error_response, success_response]) as mock_post:
			cert.reload()
			cert = apply_workflow(cert, "QM Approve")
			cert = apply_workflow(cert, "Submit HOT")
			cert = apply_workflow(cert, "HOT Approve")
			frappe.db.commit()

			self.assertEqual(cert.reload().status, "Approved")
			self.assertEqual(len(_posts(mock_post)), 1, "the first push should have been attempted")
			self.assertFalse(cert.monday_push_sent, "a failed push must not mark the certificate as sent")

			# A subsequent save (e.g., examiner updates a field) re-fires on_update_after_submit
			# and retries the push.
			cert.reload()
			cert.examiner_result = cert.examiner_result or ""
			cert.save(ignore_permissions=True)
			frappe.db.commit()
			self.assertEqual(cert.reload().status, "Approved")

		calls = _posts(mock_post)
		self.assertEqual(len(calls), 2, "the retry should have pushed exactly once more")
		self.assertEqual(_post_payload(calls[1])["variables"]["board_id"], "board_cert")
		self.assertTrue(cert.reload().monday_push_sent)
		self.assertTrue(
			frappe.get_all(
				"Error Log",
				filters={"method": "Certificate not pushed to Monday", "reference_name": cert.name},
				pluck="name",
			)
		)

	def test_session_close_pushes_to_monday(self):
		session = _session_at_assessment_complete()

		with patch("requests.post", **{"return_value": _ok_response()}) as mock_post:
			session.reload()
			session.qm_quality_check_approved = 1
			session.qm_approved_at = now_datetime()
			session.status = "CLOSED"
			session.save(ignore_permissions=True)
			frappe.db.commit()

		self.assertEqual(session.reload().status, "CLOSED")
		posts = _posts(mock_post)
		self.assertEqual(len(posts), 1)
		self.assertEqual(posts[0].kwargs["headers"]["Authorization"], "e2e-monday-token")

		variables = _post_payload(posts[0])["variables"]
		self.assertEqual(variables["board_id"], "board_session")
		self.assertEqual(variables["item_name"], f"Session {session.session_title} - CLOSED")
		columns = variables["column_values"]
		self.assertEqual(columns["session_title"], session.session_title)
		self.assertEqual(columns["course"], session.course)
		self.assertEqual(columns["status"], "CLOSED")
		self.assertEqual(columns["start_date"], str(session.start_date))
		self.assertTrue(session.reload().monday_push_sent)

	def test_session_push_is_sent_once(self):
		"""Re-saving a closed session does not push again."""
		session = _session_at_assessment_complete()

		with patch("requests.post", **{"return_value": _ok_response()}) as mock_post:
			session.reload()
			session.qm_quality_check_approved = 1
			session.qm_approved_at = now_datetime()
			session.status = "CLOSED"
			session.save(ignore_permissions=True)
			frappe.db.commit()
			self.assertEqual(len(_posts(mock_post)), 1, "closing the session should have pushed once")
			self.assertTrue(session.monday_push_sent)

			# A second save that writes nothing new must not re-fire the push.
			session.reload()
			session.status = "CLOSED"
			session.save(ignore_permissions=True)
			frappe.db.commit()

		self.assertEqual(len(_posts(mock_post)), 1, "a second save of a closed session pushed again")
		self.assertEqual(session.reload().status, "CLOSED")

	def test_session_push_skipped_when_token_empty(self):
		"""No token: nothing sent, flag stays clear, no exception, the close still holds."""
		session = _session_at_assessment_complete()
		_set_monday_settings("", "board_cert", "board_session", "board_capa")

		with patch("requests.post", **{"return_value": _ok_response()}) as mock_post:
			session.reload()
			session.qm_quality_check_approved = 1
			session.qm_approved_at = now_datetime()
			session.status = "CLOSED"
			session.save(ignore_permissions=True)
			frappe.db.commit()

		self.assertEqual(session.reload().status, "CLOSED")
		self.assertEqual(_posts(mock_post), [])
		self.assertFalse(session.monday_push_sent)
		self.assertTrue(
			frappe.get_all(
				"Error Log",
				filters={"method": "Record not pushed to Monday", "reference_name": session.name},
				pluck="name",
			)
		)

	def test_ncr_open_pushes_to_monday(self):
		with patch("requests.post", **{"return_value": _ok_response()}) as mock_post:
			ncr = _new_ncr()
			frappe.db.commit()

		posts = _posts(mock_post)
		self.assertEqual(len(posts), 1)
		self.assertEqual(posts[0].kwargs["headers"]["Authorization"], "e2e-monday-token")

		variables = _post_payload(posts[0])["variables"]
		self.assertEqual(variables["board_id"], "board_capa")
		self.assertEqual(variables["item_name"], f"NCR {ncr.name} - {ncr.exception_nature[:50]}")
		columns = variables["column_values"]
		self.assertEqual(columns["ncr_number"], ncr.name)
		self.assertEqual(columns["exception_nature"], ncr.exception_nature)
		self.assertEqual(columns["priority"], "High")
		self.assertEqual(columns["status"], "Open")
		self.assertTrue(ncr.reload().monday_push_sent)

	def test_ncr_push_not_retried_on_update(self):
		"""Editing an already-pushed Open NCR does not push again."""
		ncr = _new_ncr()
		frappe.db.commit()

		with patch("requests.post", **{"return_value": _ok_response()}) as mock_post:
			ncr.reload()
			ncr.impact_assessment = "Updated impact assessment"
			ncr.save(ignore_permissions=True)
			frappe.db.commit()

		self.assertEqual(_posts(mock_post), [], "an update to a pushed NCR pushed again")

	def test_ncr_push_skipped_when_token_empty(self):
		_set_monday_settings("", "board_cert", "board_session", "board_capa")

		with patch("requests.post", **{"return_value": _ok_response()}) as mock_post:
			ncr = _new_ncr()
			frappe.db.commit()

		self.assertEqual(ncr.status, "Open")
		self.assertEqual(_posts(mock_post), [])
		self.assertFalse(ncr.monday_push_sent)
		self.assertTrue(
			frappe.get_all(
				"Error Log",
				filters={"method": "Record not pushed to Monday", "reference_name": ncr.name},
				pluck="name",
			)
		)


def _new_ncr():
	return frappe.get_doc(
		{
			"doctype": "Nonconformity",
			"exception_nature": "E2E NCR - late certificate issuance",
			"impact_assessment": "Learner waiting for certificate",
			"responsible_person": "Administrator",
			"correction_deadline": add_days(getdate(), 30),
			"priority_level": "High",
			"status": "Open",
		}
	).insert(ignore_permissions=True)


class TestTrainingFeeAcceptance(IntegrationTestCase):
	"""5E.4: training fee payment activates the learner's enrollment."""

	def setUp(self):
		stamp = frappe.generate_hash()[:8]
		self.course = frappe.get_doc(
			{
				"doctype": "LMS Course",
				"title": f"E2E Fee Course {stamp}",
				"course_code": f"E2E-FEE-{stamp}",
				"short_introduction": "Training fee acceptance test",
				"description": "Training fee acceptance test",
				"published": 1,
			}
		).insert(ignore_permissions=True)
		learner = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"e2e-learner-{stamp}@example.com",
				"first_name": "E2E",
				"last_name": "Learner",
				"enabled": 1,
				"user_type": "Website User",
			}
		).insert(ignore_permissions=True)
		learner.add_roles("Learner")
		update_password(user=learner.name, pwd="e2e-learner")
		self.learner = learner.name

		# Real submitter per TMPM PRO-004: Training Coordinator (solange.obenson@aatc.localhost)
		self.tc = "solange.obenson@aatc.localhost"

		settings = frappe.get_single("AATC Settings")
		settings.payment_enabled = 1
		settings.payment_gateway = "Mock"
		settings.payment_mock_success_rate = 100
		settings.save(ignore_permissions=True)

	def tearDown(self):
		settings = frappe.get_single("AATC Settings")
		settings.payment_enabled = 0
		settings.save(ignore_permissions=True)

		for enrollment in frappe.get_all("LMS Enrollment", filters={"course": self.course.name}):
			frappe.delete_doc("LMS Enrollment", enrollment.name, force=1, ignore_permissions=True)
		for request in frappe.get_all(
			"Training Request", filters={"course": self.course.name}, fields=["name", "docstatus"]
		):
			if request.docstatus == 1:
				frappe.get_doc("Training Request", request.name).cancel()
			frappe.delete_doc("Training Request", request.name, force=1, ignore_permissions=True)
		frappe.delete_doc("LMS Course", self.course.name, force=1, ignore_permissions=True)
		frappe.delete_doc("User", self.learner, force=1, ignore_permissions=True)
		frappe.db.commit()

	def test_training_fee_payment_activates_enrollment(self):
		with _as(self.tc):
			request = frappe.get_doc(
				{
					"doctype": "Training Request",
					"learner": self.learner,
					"course": self.course.name,
					"requested_start_date": add_days(getdate(), 14),
				}
			).insert()
			request = apply_workflow(request, "Submit")
			self.assertEqual(request.status, "Submitted")

		with _as(frappe.get_single("AATC Settings").head_of_training):
			request = apply_workflow(request, "Approve")
			self.assertEqual(request.status, "Approved")

		enrollment = frappe.get_doc(
			{
				"doctype": "LMS Enrollment",
				"member": self.learner,
				"course": self.course.name,
				"payment_status": "Unpaid",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(enrollment.payment_status, "Unpaid")

		payment = process_training_payment(enrollment.name, amount=150000, currency="XAF")

		self.assertEqual(payment["status"], "success")
		self.assertEqual(payment["amount"], 150000)
		self.assertEqual(payment["gateway"], "Mock")
		enrollment.reload()
		self.assertEqual(enrollment.payment_status, "Paid")


class TestSettingsAcceptance(IntegrationTestCase):
	"""5E.5: AATC Settings and the named post holders are populated."""

	POST_HOLDERS = {
		"massada.apelman@aatc.localhost": "Accountable Manager",
		"avi.rozner@aatc.localhost": "Head of Training",
		"glawdys.akete@aatc.localhost": "Acting HOT",
		"jean.batoum@aatc.localhost": "Quality Manager",
		"michael.gurney@aatc.localhost": "Examination Manager",
		"solange.obenson@aatc.localhost": "Training Coordinator",
		"desmond.wangki@aatc.localhost": "DLTS",
	}

	def test_aatc_settings_all_fields_populated(self):
		# Test order is alphabetical and TestTrainingFeeAcceptance runs first, so this
		# test restores the dormant-state invariant before asserting it.
		settings = frappe.get_single("AATC Settings")
		if settings.payment_enabled:
			settings.payment_enabled = 0
			settings.save(ignore_permissions=True)
			frappe.db.commit()
		self.assertEqual(settings.accountable_manager, "massada.apelman@aatc.localhost")
		self.assertEqual(settings.head_of_training, "avi.rozner@aatc.localhost")
		self.assertEqual(settings.acting_head_of_training, "glawdys.akete@aatc.localhost")
		self.assertEqual(settings.quality_manager, "jean.batoum@aatc.localhost")
		self.assertEqual(settings.examination_manager, "michael.gurney@aatc.localhost")
		self.assertEqual(settings.paper_form_custodian, "solange.obenson@aatc.localhost")
		self.assertEqual(settings.payment_gateway, "Mock")
		self.assertIn(settings.payment_currency, ("XAF", "USD", "EUR"))
		self.assertFalse(settings.payment_enabled, "Payments stay off until a gateway is confirmed")

		users = frappe.get_all(
			"User",
			filters=[
				["name", "in", list(self.POST_HOLDERS)],
				["enabled", "=", 1],
			],
			fields=["name"],
			pluck="name",
		)
		self.assertEqual(sorted(users), sorted(self.POST_HOLDERS))
		for email, role in self.POST_HOLDERS.items():
			self.assertIn(role, frappe.get_roles(email), f"{email} is missing role {role}")


def _certificate_pending_qm():
	"""Exam PASS on a closed session; the certificate starts at Pending QM Approval."""
	session = _session_at_assessment_complete()
	exam = _exam_session(session)
	result = frappe.get_doc(
		{
			"doctype": "Examiner Result",
			"examination_session": exam.name,
			"learner": session.student,
			"score": 85,
			"examiner_decision": "PASS",
		}
	).insert(ignore_permissions=True)
	for action in ("Submit", "Verify", "Approve"):
		result = apply_workflow(result, action)

	created = create_certificates_from_exam_session(exam.name)
	assert created["certificates_created"] == 1, created

	certificate = frappe.get_all(
		"LMS Certificate", filters={"member": session.student}, pluck="name", order_by="creation desc"
	)[0]
	cert = frappe.get_doc("LMS Certificate", certificate)
	assert cert.status == "Pending QM Approval", cert.status
	return cert


def _exam_session(session):
	exam = frappe.get_doc(
		{
			"doctype": "Examination Session",
			"session": session.name,
			"session_title": session.session_title,
			"course": session.course,
			"examination_date": session.start_date,
			"start_date": session.start_date,
			"end_date": session.end_date,
		}
	).insert(ignore_permissions=True)
	for action in ("Schedule", "Start", "Complete", "Review"):
		exam = apply_workflow(exam, action)
	return exam


def _session_at_assessment_complete():
	"""Build a session with a learner enrolled and six days of attendance, committed."""
	stamp = frappe.generate_hash()[:8]
	course = frappe.get_doc(
		{
			"doctype": "LMS Course",
			"title": f"E2E Course {stamp}",
			"course_code": f"E2E-{stamp}",
			"short_introduction": "E2E acceptance",
			"description": "E2E acceptance",
			"published": 1,
		}
	).insert(ignore_permissions=True)
	student = frappe.get_doc(
		{
			"doctype": "User",
			"email": f"e2e-student-{stamp}@example.com",
			"first_name": "E2E",
			"last_name": "Student",
			"enabled": 1,
			"user_type": "Website User",
		}
	).insert(ignore_permissions=True).name
	frappe.get_doc(
		{"doctype": "LMS Enrollment", "member": student, "course": course.name, "status": "Enrolled"}
	).insert(ignore_permissions=True)

	classroom = frappe.get_doc(
		{
			"doctype": "Classroom",
			"room_code": f"E2E-CR-{stamp}",
			"room_name": f"E2E Classroom {stamp}",
			"capacity": 20,
			"location": "E2E Building",
			"inspection_status": "Inspected",
			"last_inspected_at": now_datetime(),
		}
	).insert(ignore_permissions=True)

	employee = frappe.get_all("Employee", filters={"user_id": "Administrator"}, pluck="name")
	if not employee:
		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Admin",
				"last_name": "User",
				"user_id": "Administrator",
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": "2020-01-01",
				"company": "Test Company",
				"employment_type": "Full-time",
				"status": "Active",
			}
		).insert(ignore_permissions=True).name
	else:
		employee = employee[0]
	instructor = frappe.get_doc(
		{
			"doctype": "Instructor",
			"instructor_id": f"E2E-INST-{stamp}",
			"employee": employee,
			"instructor_type": "Ground",
			"compliance_status": "Active",
			"certificate_expiry": add_days(getdate(), 365),
		}
	).insert(ignore_permissions=True)

	session = frappe.get_doc(
		{
			"doctype": "Session Lifecycle",
			"session_title": f"E2E Session {stamp}",
			"course": course.name,
			"start_date": add_days(getdate(), 10),
			"end_date": add_days(getdate(), 15),
			"status": "PLANNED",
			"instructor": instructor.name,
			"location": classroom.name,
		}
	).insert(ignore_permissions=True)
	session.update(
		{
			"instructor_availability_confirmed": 1,
			"instructor_compliance_checked": 1,
			"classroom_booked": 1,
			"equipment_check_completed": 1,
			"course_materials_version_confirmed": 1,
			"lms_shell_confirmed": 1,
			"ipad_status_confirmed": 1,
			"connectivity_test_passed": 1,
			"status": "READY FOR DELIVERY",
		}
	)
	session.save(ignore_permissions=True)
	session.update(
		{
			"go_no_go_decision": "GO",
			"tc_practical_readiness_signed": 1,
			"dlts_digital_readiness_signed": 1,
			"status": "IN PROGRESS",
		}
	)
	session.save(ignore_permissions=True)
	for offset in range(6):
		session.append(
			"daily_attendance",
			{
				"date": add_days(session.start_date, offset),
				"learner": student,
				"am_status": "Present",
				"pm_status": "Present",
				"marked_by": frappe.session.user,
				"marked_at": now_datetime(),
			},
		)
	session.update({"lms_shell_created": 1, "status": "ASSESSMENT COMPLETE"})
	session.save(ignore_permissions=True)
	# Commit so the next save has a real previous state to compare against.
	frappe.db.commit()

	session.student = student
	return session
