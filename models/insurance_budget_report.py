import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class InsuranceManagementReportHandler(models.AbstractModel):
    _name = 'insurance.management.report.handler'
    _inherit = 'account.report.custom.handler'
    _description = 'Insurance Management Accounts Custom Report Handler'

    def _custom_options_initializer(self, report, options, previous_options=None):
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        options['filter_date_range'] = True
        options['filter_journals'] = True
        
        # Force the column headers exactly as requested
        period_name = options.get('date', {}).get('string', 'Period')
        
        # Odoo uses options['column_headers'] for multi-level headers. We wipe it out so we only have one level.
        options['column_headers'] = []
        
        # The single level of headers comes from options['columns']. We rewrite them here.
        desired_names = [
            f'{period_name} Budget',
            f'{period_name} Actual',
            'Variance %',
            'YTD Budget',
            'YTD Actual',
            'Variance %',
            'Prior Year Actual',
            'Variance %'
        ]
        
        for i, col in enumerate(options.get('columns', [])):
            if i < len(desired_names):
                col['name'] = desired_names[i]

    def _custom_line_postprocessor(self, report, options, lines):
        # We intercept the computed lines to inject our custom budget and actual logic.
        col_idx = {}
        for i, col in enumerate(options.get('columns', [])):
            col_idx[col['expression_label']] = i
            
        if 'month_budget' not in col_idx:
            return lines
            
        # Parse report dates
        date_from_str = options.get('date', {}).get('date_from')
        date_to_str = options.get('date', {}).get('date_to')
        if not date_from_str or not date_to_str:
            return lines
            
        report_date_from = fields.Date.from_string(date_from_str)
        report_date_to = fields.Date.from_string(date_to_str)
        
        # Calendar Year YTD (Jan 1 to report_date_to)
        ytd_date_from = report_date_from.replace(month=1, day=1)
        
        # Prior Year Period (Same period previous year)
        py_date_from = ytd_date_from.replace(year=ytd_date_from.year - 1)
        try:
            py_date_to = report_date_to.replace(year=report_date_to.year - 1)
        except ValueError:
            # Handle leap year Feb 29
            py_date_to = report_date_to.replace(year=report_date_to.year - 1, day=28)
        
        # Determine company context
        if hasattr(report, '_get_report_company_ids'):
            company_ids = report._get_report_company_ids(options)
        else:
            company_ids = [self.env.company.id]
        
        def _get_overlap_days(d1_from, d1_to, d2_from, d2_to):
            overlap_from = max(d1_from, d2_from)
            overlap_to = min(d1_to, d2_to)
            if overlap_from <= overlap_to:
                return (overlap_to - overlap_from).days + 1
            return 0

        # 1. Fetch confirmed budget lines overlapping with YTD (which includes the current month)
        b_domain = [
            ('budget_id.state', '=', 'confirm'),
            ('company_id', 'in', company_ids),
            ('date_from', '<=', report_date_to),
            ('date_to', '>=', ytd_date_from)
        ]
        
        budget_lines = self.env['insurance.budget.line'].search(b_domain)

        # Precompute budget per account_id
        acc_month_budget = {}
        acc_ytd_budget = {}
        for bl in budget_lines:
            acc_id = bl.account_id.id
            total_days = (bl.date_to - bl.date_from).days + 1
            if total_days <= 0:
                continue
            daily = bl.planned_amount / total_days
            
            # Month overlap
            m_days = _get_overlap_days(bl.date_from, bl.date_to, report_date_from, report_date_to)
            if m_days > 0:
                acc_month_budget[acc_id] = acc_month_budget.get(acc_id, 0.0) + (daily * m_days)
                
            # YTD overlap
            y_days = _get_overlap_days(bl.date_from, bl.date_to, ytd_date_from, report_date_to)
            if y_days > 0:
                acc_ytd_budget[acc_id] = acc_ytd_budget.get(acc_id, 0.0) + (daily * y_days)

        # 2. Map accounts to report line codes
        account_to_report_line = {}
        all_accounts = self.env['account.account'].search([])
        for acc in all_accounts:
            if acc.insurance_report_category in ('management_fees_general', 'management_fees_managed'):
                account_to_report_line[acc.id] = 'INS_MGMT_OTH_OP'
            elif acc.insurance_report_category in ('other_income', 'unrealised_profit'):
                account_to_report_line[acc.id] = 'INS_MGMT_INV_INC'
            elif acc.account_type in ('income', 'income_other'):
                account_to_report_line[acc.id] = 'INS_MGMT_REV'
            elif acc.account_type == 'expense_direct_cost':
                account_to_report_line[acc.id] = 'INS_MGMT_DIR_EXP'
            elif acc.account_type in ('expense', 'expense_depreciation', 'expense_other'):
                account_to_report_line[acc.id] = 'INS_MGMT_OP_EXP'

        # Precompute budget per report line code (sum of accounts in that category)
        code_month_budget = {}
        code_ytd_budget = {}
        for acc_id, m_bud in acc_month_budget.items():
            code = account_to_report_line.get(acc_id)
            if code:
                code_month_budget[code] = code_month_budget.get(code, 0.0) + m_bud
        for acc_id, y_bud in acc_ytd_budget.items():
            code = account_to_report_line.get(acc_id)
            if code:
                code_ytd_budget[code] = code_ytd_budget.get(code, 0.0) + y_bud

        # 3. Precompute Actuals for YTD and Prior Year from account.move.line
        aml_base_domain = [
            ('display_type', 'not in', ('line_section', 'line_note')),
            ('parent_state', '=', 'posted'),
            ('company_id', 'in', company_ids),
        ]
        
        # YTD actuals query
        ytd_domain = aml_base_domain + [('date', '>=', ytd_date_from), ('date', '<=', report_date_to)]
        ytd_aml_groups = self.env['account.move.line']._read_group(
            ytd_domain,
            groupby=['account_id'],
            aggregates=['balance:sum']
        )
        acc_ytd_balance = {row[0].id: (row[1] or 0.0) for row in ytd_aml_groups if row[0]}
        
        # Prior Year actuals query
        py_domain = aml_base_domain + [('date', '>=', py_date_from), ('date', '<=', py_date_to)]
        py_aml_groups = self.env['account.move.line']._read_group(
            py_domain,
            groupby=['account_id'],
            aggregates=['balance:sum']
        )
        acc_py_balance = {row[0].id: (row[1] or 0.0) for row in py_aml_groups if row[0]}

        def _get_sign(code):
            # Revenue & Investment Income: Credit balance is positive (so multiply balance by -1)
            if code in ('INS_MGMT_REV', 'INS_MGMT_INV_INC'):
                return -1.0
            return 1.0

        acc_ytd_actual = {}
        acc_py_actual = {}
        for acc in all_accounts:
            code = account_to_report_line.get(acc.id)
            if not code:
                continue
            sign = _get_sign(code)
            if acc.id in acc_ytd_balance:
                acc_ytd_actual[acc.id] = sign * acc_ytd_balance[acc.id]
            if acc.id in acc_py_balance:
                acc_py_actual[acc.id] = sign * acc_py_balance[acc.id]

        code_ytd_actual = {}
        code_py_actual = {}
        for acc_id, val in acc_ytd_actual.items():
            code = account_to_report_line.get(acc_id)
            if code:
                code_ytd_actual[code] = code_ytd_actual.get(code, 0.0) + val
        for acc_id, val in acc_py_actual.items():
            code = account_to_report_line.get(acc_id)
            if code:
                code_py_actual[code] = code_py_actual.get(code, 0.0) + val

        # 4. Compute aggregation codes (Net Cash Flow, Operating Surplus, Surplus)
        # INS_MGMT_NET_CF = REV - DIR_EXP
        code_month_budget['INS_MGMT_NET_CF'] = code_month_budget.get('INS_MGMT_REV', 0.0) - code_month_budget.get('INS_MGMT_DIR_EXP', 0.0)
        code_ytd_budget['INS_MGMT_NET_CF'] = code_ytd_budget.get('INS_MGMT_REV', 0.0) - code_ytd_budget.get('INS_MGMT_DIR_EXP', 0.0)
        code_ytd_actual['INS_MGMT_NET_CF'] = code_ytd_actual.get('INS_MGMT_REV', 0.0) - code_ytd_actual.get('INS_MGMT_DIR_EXP', 0.0)
        code_py_actual['INS_MGMT_NET_CF'] = code_py_actual.get('INS_MGMT_REV', 0.0) - code_py_actual.get('INS_MGMT_DIR_EXP', 0.0)

        # INS_MGMT_OP_SURP = NET_CF - OP_EXP - OTH_OP
        code_month_budget['INS_MGMT_OP_SURP'] = code_month_budget.get('INS_MGMT_NET_CF', 0.0) - code_month_budget.get('INS_MGMT_OP_EXP', 0.0) - code_month_budget.get('INS_MGMT_OTH_OP', 0.0)
        code_ytd_budget['INS_MGMT_OP_SURP'] = code_ytd_budget.get('INS_MGMT_NET_CF', 0.0) - code_ytd_budget.get('INS_MGMT_OP_EXP', 0.0) - code_ytd_budget.get('INS_MGMT_OTH_OP', 0.0)
        code_ytd_actual['INS_MGMT_OP_SURP'] = code_ytd_actual.get('INS_MGMT_NET_CF', 0.0) - code_ytd_actual.get('INS_MGMT_OP_EXP', 0.0) - code_ytd_actual.get('INS_MGMT_OTH_OP', 0.0)
        code_py_actual['INS_MGMT_OP_SURP'] = code_py_actual.get('INS_MGMT_NET_CF', 0.0) - code_py_actual.get('INS_MGMT_OP_EXP', 0.0) - code_py_actual.get('INS_MGMT_OTH_OP', 0.0)

        # INS_MGMT_SURPLUS = OP_SURP + INV_INC
        code_month_budget['INS_MGMT_SURPLUS'] = code_month_budget.get('INS_MGMT_OP_SURP', 0.0) + code_month_budget.get('INS_MGMT_INV_INC', 0.0)
        code_ytd_budget['INS_MGMT_SURPLUS'] = code_ytd_budget.get('INS_MGMT_OP_SURP', 0.0) + code_ytd_budget.get('INS_MGMT_INV_INC', 0.0)
        code_ytd_actual['INS_MGMT_SURPLUS'] = code_ytd_actual.get('INS_MGMT_OP_SURP', 0.0) + code_ytd_actual.get('INS_MGMT_INV_INC', 0.0)
        code_py_actual['INS_MGMT_SURPLUS'] = code_py_actual.get('INS_MGMT_OP_SURP', 0.0) + code_py_actual.get('INS_MGMT_INV_INC', 0.0)

        # 5. Populate and format all lines
        report_lines_by_id = {rl.id: rl for rl in self.env['account.report.line'].search([('report_id', '=', report.id)])}

        for l in lines:
            parsed = report._parse_line_id(l['id'])
            line_month_budget = 0.0
            line_ytd_budget = 0.0
            line_ytd_actual = 0.0
            line_py_actual = 0.0
            
            # Case 1: Account line (when unfolded)
            if parsed and len(parsed) >= 2 and parsed[-1][1] == 'account.account':
                acc_id = parsed[-1][2]
                line_month_budget = acc_month_budget.get(acc_id, 0.0)
                line_ytd_budget = acc_ytd_budget.get(acc_id, 0.0)
                line_ytd_actual = acc_ytd_actual.get(acc_id, 0.0)
                line_py_actual = acc_py_actual.get(acc_id, 0.0)
                
            # Case 2: Section Total line (ends with total~~)
            elif parsed and parsed[-1][0] == 'total':
                parent_model = parsed[-2][1] if len(parsed) >= 2 else None
                parent_res_id = parsed[-2][2] if len(parsed) >= 2 else None
                if parent_model == 'account.report.line' and parent_res_id in report_lines_by_id:
                    code = report_lines_by_id[parent_res_id].code
                    if code:
                        line_month_budget = code_month_budget.get(code, 0.0)
                        line_ytd_budget = code_ytd_budget.get(code, 0.0)
                        line_ytd_actual = code_ytd_actual.get(code, 0.0)
                        line_py_actual = code_py_actual.get(code, 0.0)
                        
            # Case 3: Report line (header or formula aggregation line)
            elif parsed and parsed[-1][1] == 'account.report.line':
                rep_line_id = parsed[-1][2]
                if rep_line_id in report_lines_by_id:
                    code = report_lines_by_id[rep_line_id].code
                    if code:
                        line_month_budget = code_month_budget.get(code, 0.0)
                        line_ytd_budget = code_ytd_budget.get(code, 0.0)
                        line_ytd_actual = code_ytd_actual.get(code, 0.0)
                        line_py_actual = code_py_actual.get(code, 0.0)

            # Month Actual from column
            month_actual = 0.0
            if 'balance' in col_idx and len(l.get('columns', [])) > col_idx['balance']:
                col = l['columns'][col_idx['balance']]
                if col and isinstance(col, dict) and 'no_format' in col:
                    month_actual = col['no_format'] or 0.0
                    
            # Compute Variances
            # Variance % = ((Actual - Budget) / Budget) * 100
            month_variance_pct = 0.0
            if line_month_budget != 0.0:
                month_variance_pct = ((month_actual - line_month_budget) / abs(line_month_budget)) * 100.0
                
            ytd_variance_pct = 0.0
            if line_ytd_budget != 0.0:
                ytd_variance_pct = ((line_ytd_actual - line_ytd_budget) / abs(line_ytd_budget)) * 100.0
                
            py_variance_pct = 0.0
            if line_py_actual != 0.0:
                py_variance_pct = ((line_ytd_actual - line_py_actual) / abs(line_py_actual)) * 100.0

            # Inject into columns
            if 'month_budget' in col_idx and len(l.get('columns', [])) > col_idx['month_budget']:
                l['columns'][col_idx['month_budget']].update({
                    'name': report.format_value(options, line_month_budget, figure_type='monetary'),
                    'no_format': line_month_budget,
                    'is_zero': line_month_budget == 0.0
                })
            if 'month_variance_pct' in col_idx and len(l.get('columns', [])) > col_idx['month_variance_pct']:
                l['columns'][col_idx['month_variance_pct']].update({
                    'name': report.format_value(options, month_variance_pct, figure_type='percentage'),
                    'no_format': month_variance_pct,
                    'is_zero': month_variance_pct == 0.0
                })
            if 'ytd_budget' in col_idx and len(l.get('columns', [])) > col_idx['ytd_budget']:
                l['columns'][col_idx['ytd_budget']].update({
                    'name': report.format_value(options, line_ytd_budget, figure_type='monetary'),
                    'no_format': line_ytd_budget,
                    'is_zero': line_ytd_budget == 0.0
                })
            if 'ytd_actual' in col_idx and len(l.get('columns', [])) > col_idx['ytd_actual']:
                l['columns'][col_idx['ytd_actual']].update({
                    'name': report.format_value(options, line_ytd_actual, figure_type='monetary'),
                    'no_format': line_ytd_actual,
                    'is_zero': line_ytd_actual == 0.0
                })
            if 'ytd_variance_pct' in col_idx and len(l.get('columns', [])) > col_idx['ytd_variance_pct']:
                l['columns'][col_idx['ytd_variance_pct']].update({
                    'name': report.format_value(options, ytd_variance_pct, figure_type='percentage'),
                    'no_format': ytd_variance_pct,
                    'is_zero': ytd_variance_pct == 0.0
                })
            if 'prior_year_actual' in col_idx and len(l.get('columns', [])) > col_idx['prior_year_actual']:
                l['columns'][col_idx['prior_year_actual']].update({
                    'name': report.format_value(options, line_py_actual, figure_type='monetary'),
                    'no_format': line_py_actual,
                    'is_zero': line_py_actual == 0.0
                })
            if 'prior_year_variance_pct' in col_idx and len(l.get('columns', [])) > col_idx['prior_year_variance_pct']:
                l['columns'][col_idx['prior_year_variance_pct']].update({
                    'name': report.format_value(options, py_variance_pct, figure_type='percentage'),
                    'no_format': py_variance_pct,
                    'is_zero': py_variance_pct == 0.0
                })
                    
        return lines
