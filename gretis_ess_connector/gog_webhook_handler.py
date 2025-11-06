import frappe
import requests
import json
import traceback

def create_log(status, doc, payload, response_text="", tb=""):
    """Creates a GOG Webhook Log record."""
    try:
        log = frappe.new_doc("GOG Webhook Log")
        log.status = status
        log.reference_doctype = doc.doctype
        log.reference_name = doc.name
        log.request_payload = json.dumps(payload, indent=2, default=str)
        log.response = response_text
        log.error_traceback = tb
        # Use ignore_permissions to ensure the log is always created, even if called by a user
        # who doesn't have direct permission on the log doctype.
        log.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        # If logging itself fails, write to the main error log as a last resort.
        frappe.log_error(title="Failed to Create GOG Webhook Log", message=traceback.format_exc())


@frappe.whitelist()
def trigger_webhook_for_doc(doc, method):
    """
    Main function called by the 'validate' hook. It checks for a status change
    before queueing the background job.
    """
    try:
        # The 'validate' hook runs on every save. We only care about existing, submitted documents.
        if not doc.is_new() and doc.docstatus == 1:
            # Get the state of the document *before* this save operation from the database
            old_doc = doc.get_doc_before_save()
            
            # If there's no old_doc, it means something is unusual, so we can't compare.
            if not old_doc:
                return

            # Determine the correct status field based on DocType
            status_field = "status"
            if doc.doctype == "Expense Claim":
                status_field = "approval_status"

            old_status = old_doc.get(status_field)
            new_status = doc.get(status_field)

            # Check if the status has actually changed to a state we care about
            if new_status != old_status and new_status in ["Approved", "Rejected"]:
                
                # The status has changed! Now we can enqueue the job.
                settings = frappe.get_single("GOG Settings")
                if not settings.enable_webhooks:
                    return

                # Collect all relevant info to pass to the background job
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

                # Run the actual sending logic in the background to not slow down the user's save action.
                frappe.enqueue(
                    "gretis_ess_connector.gretis_ess_connector.gog_webhook_handler.send_request",
                    doc_info=doc_info,
                    settings_info={
                        "url": settings.webhook_url,
                        "secret": settings.get_password('webhook_secret')
                    }
                )

    except Exception:
        # If the enqueue call itself fails, log it to the main error log.
        frappe.log_error(title="GOG Webhook Enqueue Failed", message=traceback.format_exc())


def send_request(doc_info, settings_info):
    """
    This function runs in a background worker. It builds the payload,
    sends the request, and creates the log record.
    """
    payload = {}
    # We create a temporary mock 'doc' object to pass to the logger, so it has the right shape.
    mock_doc_for_logging = frappe._dict({"doctype": doc_info["doctype"], "name": doc_info["name"]})

    try:
        # The main condition check is already done in the trigger, but we can keep it for safety.
        doc_status = doc_info.get("status") or doc_info.get("approval_status")
        if doc_status not in ["Approved", "Rejected"]:
            return

        # Build the payload based on doctype
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
            # Not a doctype we are configured to handle.
            return

        headers = {
            "Content-Type": "application/json",
            "x-webhook-secret": settings_info["secret"]
        }

        response = requests.post(
            settings_info["url"],
            data=json.dumps(payload, default=str),
            headers=headers,
            timeout=15 # A slightly longer timeout for network operations
        )
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)

        create_log("Success", mock_doc_for_logging, payload, response.text)

    except Exception:
        # If any part of the background job fails, log the full error.
        tb = traceback.format_exc()
        create_log("Error", mock_doc_for_logging, payload, tb=tb)
