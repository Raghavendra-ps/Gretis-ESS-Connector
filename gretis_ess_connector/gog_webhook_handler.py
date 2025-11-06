import frappe
import requests
import json
import traceback

def create_log(status, doc, payload, response_text="", tb=""):
    """Creates a GOG Webhook Log record."""
    log = frappe.new_doc("GOG Webhook Log")
    log.status = status
    log.reference_doctype = doc.doctype
    log.reference_name = doc.name
    log.request_payload = json.dumps(payload, indent=2, default=str)
    log.response = response_text
    log.error_traceback = tb
    log.save(ignore_permissions=True)
    frappe.db.commit()

@frappe.whitelist()
def trigger_webhook_for_doc(doc, method):
    """
    Main function called by the hook. It reads settings, prepares data,
    and calls the sender function in the background.
    """
    try:
        settings = frappe.get_single("GOG Settings")
        if not settings.enable_webhooks:
            return # Do nothing if the master switch is off.

        # Prepare a dictionary of basic info to pass to the background job
        doc_info = {
            "doctype": doc.doctype,
            "name": doc.name,
            "status": doc.get("status"),
            "approval_status": doc.get("approval_status"),
            "employee": doc.get("employee"),
            "title": doc.get("title"),
            "from_date": doc.get("from_date"),
            "explanation": doc.get("explanation")
        }

        # Run the actual sending logic in the background
        frappe.enqueue(
            "gretis_ess_connector.gretis_ess_connector.gog_webhook_handler.send_request",
            doc_info=doc_info,
            settings_info={
                "url": settings.webhook_url,
                "secret": settings.get_password('webhook_secret')
            }
        )
    except Exception:
        # If the enqueue fails, log it immediately.
        frappe.log_error(title="GOG Webhook Enqueue Failed", message=traceback.format_exc())


def send_request(doc_info, settings_info):
    """
    This function runs in a background worker. It builds the payload,
    sends the request, and creates the log record.
    """
    payload = {}
    try:
        # Re-check the conditions within the background job
        doc_status = doc_info.get("status") or doc_info.get("approval_status")
        if doc_status not in ["Approved", "Rejected"]:
            return

        payload = {"doctype": doc_info["doctype"], "employee": doc_info["employee"]}
        if doc_info["doctype"] == "Attendance Request":
            payload.update({
                "status": doc_info["status"],
                "from_date": doc_info["from_date"],
                "explanation": doc_info["explanation"]
            })
        elif doc_info["doctype"] == "Leave Application":
            payload.update({"status": doc_info["status"]})
        elif doc_info["doctype"] == "Expense Claim":
            payload.update({"approval_status": doc_info["approval_status"], "title": doc_info["title"]})
        else:
            return # Should not happen, but good to have a safeguard

        headers = {
            "Content-Type": "application/json",
            "x-webhook-secret": settings_info["secret"]
        }

        response = requests.post(
            settings_info["url"],
            data=json.dumps(payload, default=str),
            headers=headers,
            timeout=15
        )
        response.raise_for_status()

        create_log("Success", frappe.get_doc(doc_info["doctype"], doc_info["name"]), payload, response.text)

    except Exception:
        tb = traceback.format_exc()
        create_log("Error", frappe.get_doc(doc_info["doctype"], doc_info["name"]), payload, tb=tb)
