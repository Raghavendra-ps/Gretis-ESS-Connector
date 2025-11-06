doc_events = {
    "Attendance Request": {
        "on_update": "gretis_ess_connector.gretis_ess_connector.gog_webhook_handler.trigger_webhook_for_doc"
    },
    "Leave Application": {
        "on_update": "gretis_ess_connector.gretis_ess_connector.gog_webhook_handler.trigger_webhook_for_doc"
    },
    "Expense Claim": {
        "on_update": "gretis_ess_connector.gretis_ess_connector.gog_webhook_handler.trigger_webhook_for_doc"
    }
}
