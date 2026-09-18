from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date

class InsuranceBudget(models.Model):
    _name = 'insurance.budget'
    _description = 'Insurance Annual / Monthly Budget'
    _inherit = ['analytic.mixin']
    _order = 'date_from desc, id desc'

    name = fields.Char(string="Budget Name", required=True, default=lambda self: _("%s Annual Budget") % date.today().year)
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string="Currency")
    date_from = fields.Date(string="Start Date", required=True, default=lambda self: date(date.today().year, 1, 1))
    date_to = fields.Date(string="End Date", required=True, default=lambda self: date(date.today().year, 12, 31))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirmed'),
        ('cancel', 'Cancelled')
    ], string="Status", default='draft', required=True)

    line_ids = fields.One2many('insurance.budget.line', 'budget_id', string="Budget Items", copy=True)

    def action_confirm(self):
        self.write({'state': 'confirm'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_prefill_pnl_accounts(self):
        """Prefills budget lines with all P&L accounts (Income, Expense, Direct Cost)"""
        self.ensure_one()
        Account = self.env['account.account']
        
        # Search all Income and Expense accounts
        pnl_accounts = Account.search([
            ('account_type', 'in', (
                'income', 'income_other', 
                'expense', 'expense_depreciation', 'expense_direct_cost', 'expense_other'
            ))
        ])

        existing_account_ids = self.line_ids.mapped('account_id.id')
        new_lines = []
        
        for acc in pnl_accounts:
            if acc.id not in existing_account_ids:
                new_lines.append((0, 0, {
                    'account_id': acc.id,
                    'analytic_distribution': self.analytic_distribution if self.analytic_distribution else False,
                    'planned_amount': 0.0,
                    'date_from': self.date_from,
                    'date_to': self.date_to,
                }))
        
        if new_lines:
            self.write({'line_ids': new_lines})
        return True


class InsuranceBudgetLine(models.Model):
    _name = 'insurance.budget.line'
    _description = 'Insurance Budget Line'
    _inherit = ['analytic.mixin']
    _order = 'account_id asc, date_from asc'

    budget_id = fields.Many2one('insurance.budget', string="Budget", required=True, ondelete='cascade')
    company_id = fields.Many2one(related='budget_id.company_id', store=True)
    currency_id = fields.Many2one(related='budget_id.currency_id')
    account_id = fields.Many2one(
        'account.account', 
        string="Account", 
        required=True,
        domain="[('account_type', 'in', ('income', 'income_other', 'expense', 'expense_depreciation', 'expense_direct_cost', 'expense_other'))]"
    )
    date_from = fields.Date(string="Start Date", required=True)
    date_to = fields.Date(string="End Date", required=True)
    planned_amount = fields.Monetary(string="Amount", required=True, default=0.0)
    comment = fields.Char(string="Comment")
