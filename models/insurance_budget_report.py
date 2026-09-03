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
        # We intercept the computed lines to inject our custom budget logic.
        col_idx = {}
        for i, col in enumerate(options.get('columns', [])):
            col_idx[col['expression_label']] = i
            
        if 'month_budget' not in col_idx:
            return lines
            
        from datetime import datetime
        # Parse report dates
        date_from_str = options['date'].get('date_from')
        date_to_str = options['date'].get('date_to')
        if not date_from_str or not date_to_str:
            return lines
            
        report_date_from = fields.Date.from_string(date_from_str)
        report_date_to = fields.Date.from_string(date_to_str)
        
        # Calculate YTD dates based on Odoo standard or simple assumption (Jan 1st to report date)
        ytd_date_from = report_date_from.replace(month=1, day=1)
        
        # Fetch all confirmed budget lines overlapping with YTD (which includes the month)
        domain = [
            ('budget_id.state', '=', 'confirm'),
            ('date_from', '<=', report_date_to),
            ('date_to', '>=', ytd_date_from)
        ]
        
        # Apply analytic account filtering if selected in the report options
        if options.get('analytic_accounts'):
            domain.append(('distribution_analytic_account_ids', 'in', options['analytic_accounts']))
            
        budget_lines = self.env['insurance.budget.line'].search(domain)
        
        # Map accounts to report line codes
        account_to_report_line = {}
        for acc in self.env['account.account'].search([]):
            acc_name = acc.name.lower()
            if 'recurring' in acc_name:
                account_to_report_line[acc.id] = 'INS_MGMT_REV_REC'
            elif 'new business' in acc_name:
                account_to_report_line[acc.id] = 'INS_MGMT_REV_NEW'
            elif 'managed fund' in acc_name and 'management fee' not in acc_name:
                account_to_report_line[acc.id] = 'INS_MGMT_REV_MAN'
            elif 'management fee' in acc_name and 'general' in acc_name:
                account_to_report_line[acc.id] = 'INS_MGMT_MGT_GEN'
            elif 'management fee' in acc_name and 'managed' in acc_name:
                account_to_report_line[acc.id] = 'INS_MGMT_MGT_MAN'
            elif acc.account_type == 'expense_direct_cost':
                account_to_report_line[acc.id] = 'INS_MGMT_DIR_EXP'
            elif acc.account_type in ('expense', 'expense_depreciation', 'expense_other') and acc.insurance_report_category == False:
                account_to_report_line[acc.id] = 'INS_MGMT_OP_EXP'
            elif acc.insurance_report_category == 'other_income':
                account_to_report_line[acc.id] = 'INS_MGMT_OTH_INC'
            elif acc.insurance_report_category == 'unrealised_profit':
                account_to_report_line[acc.id] = 'INS_MGMT_UNREAL_PROF'

        # Precompute budget amounts per report line code
        line_code_month_budget = {}
        line_code_ytd_budget = {}
        
        def _get_overlap_days(d1_from, d1_to, d2_from, d2_to):
            overlap_from = max(d1_from, d2_from)
            overlap_to = min(d1_to, d2_to)
            if overlap_from <= overlap_to:
                return (overlap_to - overlap_from).days + 1
            return 0
            
        for line in budget_lines:
            acc_id = line.account_id.id
            code = account_to_report_line.get(acc_id)
            if not code:
                continue
                
            total_days = (line.date_to - line.date_from).days + 1
            if total_days <= 0:
                continue
            daily_amount = line.planned_amount / total_days
            
            # Month overlap
            month_days = _get_overlap_days(line.date_from, line.date_to, report_date_from, report_date_to)
            if month_days > 0:
                line_code_month_budget[code] = line_code_month_budget.get(code, 0.0) + (daily_amount * month_days)
                
            # YTD overlap
            ytd_days = _get_overlap_days(line.date_from, line.date_to, ytd_date_from, report_date_to)
            if ytd_days > 0:
                line_code_ytd_budget[code] = line_code_ytd_budget.get(code, 0.0) + (daily_amount * ytd_days)

        # Map lines by id for easy access
        line_by_id = {l['id']: l for l in lines}
        
        # Inject budget into lines
        for l in lines:
            l['month_budget'] = 0.0
            l['ytd_budget'] = 0.0
            l['prior_year_actual'] = 0.0
            
            model, res_id = report._get_model_info_from_id(l['id'])
            
            # If it is a parent report line
            if model == 'account.report.line' and res_id:
                rep_line = self.env['account.report.line'].browse(res_id)
                if rep_line.code:
                    l['month_budget'] = line_code_month_budget.get(rep_line.code, 0.0)
                    l['ytd_budget'] = line_code_ytd_budget.get(rep_line.code, 0.0)
            
            # If it is an account child line (unfolded)
            elif model == 'account.account' and res_id:
                code = account_to_report_line.get(res_id)
                if code:
                    # In Odoo, child lines don't natively aggregate budget in postprocessor unless we do it. 
                    # But if we assign to the child, we must NOT assign to the parent again, or it will double count.
                    # Since we want to support folded (parent only) AND unfolded (children + parent),
                    # we should actually calculate bottom-up!
                    pass

        # To handle both folded and unfolded correctly, we should assign budget to the `report.line` (parents),
        # but wait, if it's unfolded, does the report automatically sum children in postprocessor? No.
        # Actually, if we just assign the budget to the parent `report.line`, it will show on the parent.
        # But if we also assign it to the children, the backward iteration will sum it again and double it!
        # So it's safer to just inject it on the parent `report.line` directly and NOT on the children, 
        # or clear the parent before the backward loop. Let's clear parent before loop.

        # Let's just rely on the backward loop for aggregation of hierarchies (e.g. INS_MGMT_TOT_REV)
        # We need to compute formulas for aggregated lines!
        # e.g., INS_MGMT_TOT_REV = INS_MGMT_REV_REC + INS_MGMT_REV_NEW + INS_MGMT_REV_MAN
        
        # First, ensure all parent report lines have their base budget
        for l in lines:
            model, res_id = report._get_model_info_from_id(l['id'])
            if model == 'account.report.line' and res_id:
                rep_line = self.env['account.report.line'].browse(res_id)
                code = rep_line.code
                if code:
                    l['code'] = code
                    # If this line has direct budget (not a formula total)
                    if code in line_code_month_budget:
                        l['month_budget'] = line_code_month_budget.get(code, 0.0)
                        l['ytd_budget'] = line_code_ytd_budget.get(code, 0.0)

        # Map lines by code
        line_by_code = {l.get('code'): l for l in lines if l.get('code')}

        # Calculate formulas
        def get_val(code, field):
            return line_by_code.get(code, {}).get(field, 0.0)

        # INS_MGMT_TOT_REV
        if 'INS_MGMT_TOT_REV' in line_by_code:
            line_by_code['INS_MGMT_TOT_REV']['month_budget'] = get_val('INS_MGMT_REV_REC', 'month_budget') + get_val('INS_MGMT_REV_NEW', 'month_budget') + get_val('INS_MGMT_REV_MAN', 'month_budget')
            line_by_code['INS_MGMT_TOT_REV']['ytd_budget'] = get_val('INS_MGMT_REV_REC', 'ytd_budget') + get_val('INS_MGMT_REV_NEW', 'ytd_budget') + get_val('INS_MGMT_REV_MAN', 'ytd_budget')

        # INS_MGMT_NET_CF
        if 'INS_MGMT_NET_CF' in line_by_code:
            line_by_code['INS_MGMT_NET_CF']['month_budget'] = get_val('INS_MGMT_TOT_REV', 'month_budget') - get_val('INS_MGMT_DIR_EXP', 'month_budget')
            line_by_code['INS_MGMT_NET_CF']['ytd_budget'] = get_val('INS_MGMT_TOT_REV', 'ytd_budget') - get_val('INS_MGMT_DIR_EXP', 'ytd_budget')

        # INS_MGMT_TOT_OTH_OP
        if 'INS_MGMT_TOT_OTH_OP' in line_by_code:
            line_by_code['INS_MGMT_TOT_OTH_OP']['month_budget'] = get_val('INS_MGMT_MGT_GEN', 'month_budget') + get_val('INS_MGMT_MGT_MAN', 'month_budget')
            line_by_code['INS_MGMT_TOT_OTH_OP']['ytd_budget'] = get_val('INS_MGMT_MGT_GEN', 'ytd_budget') + get_val('INS_MGMT_MGT_MAN', 'ytd_budget')

        # INS_MGMT_OP_SURP
        if 'INS_MGMT_OP_SURP' in line_by_code:
            line_by_code['INS_MGMT_OP_SURP']['month_budget'] = get_val('INS_MGMT_NET_CF', 'month_budget') - get_val('INS_MGMT_OP_EXP', 'month_budget') - get_val('INS_MGMT_TOT_OTH_OP', 'month_budget')
            line_by_code['INS_MGMT_OP_SURP']['ytd_budget'] = get_val('INS_MGMT_NET_CF', 'ytd_budget') - get_val('INS_MGMT_OP_EXP', 'ytd_budget') - get_val('INS_MGMT_TOT_OTH_OP', 'ytd_budget')

        # INS_MGMT_TOT_INV_INC
        if 'INS_MGMT_TOT_INV_INC' in line_by_code:
            line_by_code['INS_MGMT_TOT_INV_INC']['month_budget'] = get_val('INS_MGMT_OTH_INC', 'month_budget') + get_val('INS_MGMT_UNREAL_PROF', 'month_budget')
            line_by_code['INS_MGMT_TOT_INV_INC']['ytd_budget'] = get_val('INS_MGMT_OTH_INC', 'ytd_budget') + get_val('INS_MGMT_UNREAL_PROF', 'ytd_budget')

        # INS_MGMT_SURPLUS
        if 'INS_MGMT_SURPLUS' in line_by_code:
            line_by_code['INS_MGMT_SURPLUS']['month_budget'] = get_val('INS_MGMT_OP_SURP', 'month_budget') + get_val('INS_MGMT_TOT_INV_INC', 'month_budget')
            line_by_code['INS_MGMT_SURPLUS']['ytd_budget'] = get_val('INS_MGMT_OP_SURP', 'ytd_budget') + get_val('INS_MGMT_TOT_INV_INC', 'ytd_budget')
                
        # Now format and inject into columns
        for l in lines:
            month_actual = 0.0
            if 'balance' in col_idx and len(l.get('columns', [])) > col_idx['balance']:
                col = l['columns'][col_idx['balance']]
                if col and isinstance(col, dict) and 'no_format' in col:
                    month_actual = col['no_format'] or 0.0
            
            month_budget = l.get('month_budget', 0.0)
            month_variance_pct = 0.0
            if month_budget != 0.0:
                month_variance_pct = ((month_actual - month_budget) / abs(month_budget)) * 100
                
            ytd_actual = 0.0
            if 'ytd_actual' in col_idx and len(l.get('columns', [])) > col_idx['ytd_actual']:
                col = l['columns'][col_idx['ytd_actual']]
                if col and isinstance(col, dict) and 'no_format' in col:
                    ytd_actual = col['no_format'] or 0.0
            ytd_budget = l.get('ytd_budget', 0.0)
            ytd_variance_pct = 0.0
            if ytd_budget != 0.0:
                ytd_variance_pct = ((ytd_actual - ytd_budget) / abs(ytd_budget)) * 100
                
            prior_year_actual = l.get('prior_year_actual', 0.0)
            py_variance_pct = 0.0
            if prior_year_actual != 0.0:
                py_variance_pct = ((ytd_actual - prior_year_actual) / abs(prior_year_actual)) * 100
                
            # Update columns
            if 'month_budget' in col_idx and len(l.get('columns', [])) > col_idx['month_budget']:
                l['columns'][col_idx['month_budget']].update({
                    'name': report.format_value(options, month_budget, figure_type='monetary'),
                    'no_format': month_budget,
                    'is_zero': month_budget == 0.0
                })
            if 'month_variance_pct' in col_idx and len(l.get('columns', [])) > col_idx['month_variance_pct']:
                l['columns'][col_idx['month_variance_pct']].update({
                    'name': report.format_value(options, month_variance_pct, figure_type='percentage'),
                    'no_format': month_variance_pct,
                    'is_zero': month_variance_pct == 0.0
                })
            if 'ytd_budget' in col_idx and len(l.get('columns', [])) > col_idx['ytd_budget']:
                l['columns'][col_idx['ytd_budget']].update({
                    'name': report.format_value(options, ytd_budget, figure_type='monetary'),
                    'no_format': ytd_budget,
                    'is_zero': ytd_budget == 0.0
                })
            if 'ytd_variance_pct' in col_idx and len(l.get('columns', [])) > col_idx['ytd_variance_pct']:
                l['columns'][col_idx['ytd_variance_pct']].update({
                    'name': report.format_value(options, ytd_variance_pct, figure_type='percentage'),
                    'no_format': ytd_variance_pct,
                    'is_zero': ytd_variance_pct == 0.0
                })
            if 'prior_year_actual' in col_idx and len(l.get('columns', [])) > col_idx['prior_year_actual']:
                l['columns'][col_idx['prior_year_actual']].update({
                    'name': report.format_value(options, prior_year_actual, figure_type='monetary'),
                    'no_format': prior_year_actual,
                    'is_zero': prior_year_actual == 0.0
                })
            if 'prior_year_variance_pct' in col_idx and len(l.get('columns', [])) > col_idx['prior_year_variance_pct']:
                l['columns'][col_idx['prior_year_variance_pct']].update({
                    'name': report.format_value(options, py_variance_pct, figure_type='percentage'),
                    'no_format': py_variance_pct,
                    'is_zero': py_variance_pct == 0.0
                })
                    
        return lines
