# Enterprise Budget Management & Management Accounts (budget)

[![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20%7C%2018.0%20%7C%2019.0-714B67?logo=odoo&logoColor=white)](https://www.odoo.com)
[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](LICENSE)
[![Category](https://img.shields.io/badge/Category-Accounting%2FFinance-orange.svg)]()
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen.svg)]()

> **Standalone Financial Budget Management, Budget vs. Actual Variance Reporting & Dynamic Management Accounts for Odoo.**

---

## 📌 Overview

**Enterprise Budget Management & Management Accounts** delivers full-cycle financial budget creation, line-level expense allocation, and real-time variance analysis against general ledger actuals. Built to support complex corporate hierarchies and insurance management accounting, it eliminates manual spreadsheet consolidations with dynamic report generation.

---

## ✨ Key Features

### 1. 📊 Budget vs. Actual Reporting
- Compare planned budgetary allocations directly against posted General Ledger transactions (`account.move.line`).
- Automatic computation of variance amounts and variance percentages.

### 2. 📑 Insurance Management Accounts Integration
- Tight integration with `insurance_profit_and_loss` providing multi-dimensional management accounting views.
- Dynamic parsing of line totals, direct actuals calculation, and branch/cost center breakdowns.

### 3. 🛡️ Analytic & Departmental Control
- Track budget consumption by analytic account, project, department, or cost center.
- Over-budget alerts and threshold monitoring before payments or expenses are approved.

---

## 📁 Technical Information

| Attribute | Value |
|---|---|
| **Technical Name** | `budget` |
| **Category** | Accounting / Finance |
| **Odoo Compatibility** | Odoo 17.0+ & 18.0+ & 19.0+ |
| **Dependencies** | `base`, `account`, `analytic`, `account_reports`, `insurance_profit_and_loss` |
| **License** | LGPL-3 |
| **Maintainer** | DraftPOS & Havano Solutions |

---

## 📄 License

This module is licensed under the **GNU Lesser General Public License v3.0 (LGPL-3)**. See the [LICENSE](LICENSE) file for details.
