import frappe
from frappe.model.document import Document
from typing import Optional, List, Dict, Any


class StudentTranscript(Document):
    pass


@frappe.whitelist()
def get_data(
    filters: Optional[Dict[str, Any]] = None,
    fields: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0,
    order_by: Optional[str] = None,
    **kwargs: Any
) -> List[Dict[str, Any]]:
    """
    Virtual DocType get_data method for Student Transcript.
    Builds transcript data from LMS Enrollment records with custom fields.
    """
    if isinstance(filters, str):
        import json
        filters = json.loads(filters)

    # Build base query from LMS Enrollment with custom fields
    query_filters = []
    if filters:
        for key, value in filters.items():
            if key == "student":
                query_filters.append(["LMS Enrollment", "member", "=", value])
            elif key == "course":
                query_filters.append(["LMS Enrollment", "course", "=", value])
            elif key == "enrollment":
                query_filters.append(["LMS Enrollment", "name", "=", value])
            elif key == "final_grade":
                query_filters.append(["LMS Enrollment", "final_grade", "=", value])
            elif key == "examiner_decision":
                query_filters.append(["LMS Enrollment", "examiner_decision", "=", value])
            elif key == "certificate_issued":
                query_filters.append(["LMS Enrollment", "certificate_issued", "=", value])

    # Get enrollment records
    enrollments = frappe.get_all(
        "LMS Enrollment",
        filters=query_filters,
        fields=[
            "name",
            "member",
            "member_name",
            "course",
            "final_grade",
            "grade_points",
            "exam_score",
            "attendance_score",
            "examiner_decision",
            "certificate_issued",
            "certificate_expiry",
            "exam_session",
            "creation",
            "modified"
        ],
        limit=limit,
        offset=offset,
        order_by=order_by or "creation desc"
    )

    # Get certificate data for each enrollment
    result = []
    for enroll in enrollments:
        # Fetch course title from LMS Course
        course_title = ""
        if enroll.course:
            course_doc = frappe.get_cached_value("LMS Course", enroll.course, "title")
            course_title = course_doc or ""

        # Get certificate if issued
        certificate = None
        certificate_number = None
        if enroll.certificate_issued:
            certificate = frappe.get_all(
                "LMS Certificate",
                filters={"member": enroll.member, "course": enroll.course},
                fields=["name", "certificate_number", "expiry_date", "status"],
                limit=1
            )
            if certificate:
                certificate_number = certificate[0].get("certificate_number")
                cert_expiry = certificate[0].get("expiry_date")
            else:
                cert_expiry = enroll.certificate_expiry
        else:
            cert_expiry = enroll.certificate_expiry

        # Get exam session details
        completion_date = None
        if enroll.exam_session:
            exam_session = frappe.get_doc("Examination Session", enroll.exam_session)
            if exam_session.examination_date:
                completion_date = exam_session.examination_date

        result.append({
            "student": enroll.member,
            "student_name": enroll.member_name,
            "course": enroll.course,
            "course_title": course_title,
            "enrollment": enroll.name,
            "final_grade": enroll.final_grade,
            "grade_points": enroll.grade_points,
            "exam_score": enroll.exam_score,
            "attendance_score": enroll.attendance_score,
            "examiner_decision": enroll.examiner_decision,
            "certificate_issued": enroll.certificate_issued,
            "certificate_number": certificate_number,
            "certificate_expiry": cert_expiry,
            "exam_session": enroll.exam_session,
            "completion_date": completion_date
        })

    return result


@frappe.whitelist()
def get_count(filters: Optional[Dict[str, Any]] = None, **kwargs: Any) -> int:
    """Get count of transcript records for pagination."""
    if isinstance(filters, str):
        import json
        filters = json.loads(filters)

    query_filters = []
    if filters:
        for key, value in filters.items():
            if key == "student":
                query_filters.append(["LMS Enrollment", "member", "=", value])
            elif key == "course":
                query_filters.append(["LMS Enrollment", "course", "=", value])
            elif key == "enrollment":
                query_filters.append(["LMS Enrollment", "name", "=", value])
            elif key == "final_grade":
                query_filters.append(["LMS Enrollment", "final_grade", "=", value])
            elif key == "examiner_decision":
                query_filters.append(["LMS Enrollment", "examiner_decision", "=", value])
            elif key == "certificate_issued":
                query_filters.append(["LMS Enrollment", "certificate_issued", "=", value])

    return frappe.db.count("LMS Enrollment", filters=query_filters)