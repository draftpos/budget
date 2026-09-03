{
    "name": "Budget",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "summary": "Standalone Budget Management and Management Accounts (Budget vs Actual) reporting",
    "author": "Havano",
    "license": "LGPL-3",
    "depends": [
        "base",
        "account",
        "account_reports",
        "insurance_profit_and_loss",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/insurance_budget_views.xml",
        "data/insurance_budget_vs_actual_report.xml",
    ],
    "installable": True,
    "application": True,
}
