# -*- coding: utf-8 -*-
# (c) 2016 Alfredo de la Fuente - AvanzOSC
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html
from openerp import models, api, fields, exceptions, _
from dateutil.relativedelta import relativedelta


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    project_by_task = fields.Selection(
        [('yes', 'Yes'),
         ('no', 'No')], string='Create project by task')

    @api.multi
    def action_button_confirm(self):
        project_obj = self.env['project.project']
        if not self.env.user.tz:
            raise exceptions.Warning(_('User without time zone'))
        if not self.project_id:
            raise exceptions.Warning(_('You must enter the project/contract'))
        if not self.project_id.date_start:
            raise exceptions.Warning(_('You must enter the start date of the'
                                       ' project/contract'))
        if not self.project_id.date:
            raise exceptions.Warning(_('You must enter the end date of the'
                                       ' project/contract'))
        self.project_id.sale = self.id
        cond = [('analytic_account_id', '=', self.project_id.id)]
        project = project_obj.search(cond, limit=1)
        if not project:
            raise exceptions.Warning(_('Project/contract without project'))
        res = super(SaleOrder, self).action_button_confirm()
        self._create_event_and_sessions_from_sale_order()
        return res

    def _create_event_and_sessions_from_sale_order(self):
        event_obj = self.env['event.event']
        project_obj = self.env['project.project']
        for sale in self:
            sale_lines = sale.order_line.filtered(
                lambda x: x.recurring_service)
            if sale_lines and sale.project_by_task == 'no':
                event = event_obj._create_event_from_sale(False, sale)
            for line in sale_lines:
                if sale.project_by_task == 'yes':
                    event = event_obj._create_event_from_sale(True, sale,
                                                              line=line)
                num_session = 0
                sale._validate_create_session_from_sale_order(
                    event, num_session, line)
                if sale.project_by_task == 'yes':
                    name = sale.name + ': ' + line.name
                    cond = [('name', '=', name)]
                    project = project_obj.search(cond, limit=1)
                    project.event_id = event.id
                sale.project_id.name = sale.name

    def _prepare_event_data(self, sale, name, project):
        event_obj = self.env['event.event']
        event_vals = ({'name': name,
                       'timezone_of_event': self.env.user.tz,
                       'date_tz': self.env.user.tz,
                       'project_id': project.id,
                       'sale_order': sale.id})
        utc_dt = event_obj._put_utc_format_date(self.project_id.date_start,
                                                0.0)
        event_vals['date_begin'] = utc_dt
        utc_dt = event_obj._put_utc_format_date(self.project_id.date, 0.0)
        event_vals['date_end'] = utc_dt
        return event_vals

    def _validate_create_session_from_sale_order(self, event, num_session,
                                                 line):
        task_obj = self.env['project.task']
        fec_ini = fields.Datetime.from_string(
            self.project_id.date_start).date()
        if fec_ini.day != 1:
            while fec_ini.day != 1:
                fec_ini = fec_ini + relativedelta(days=-1)
        if fec_ini.weekday() == 0:
            num_week = 0
        else:
            num_week = 1
        month = fec_ini.month
        while (fec_ini <=
               fields.Datetime.from_string(self.project_id.date).date()):
            if month != fec_ini.month:
                month = fec_ini.month
                if fec_ini.weekday() == 0:
                    num_week = 0
                else:
                    num_week = 1
            if fec_ini.weekday() == 0:
                num_week += 1
            if fec_ini >= fields.Datetime.from_string(
                    self.project_id.date_start).date():
                valid = task_obj._validate_event_session_month(line, fec_ini)
                if valid:
                    valid = task_obj._validate_event_session_week(
                        line, num_week)
                if valid:
                    valid = task_obj._validate_event_session_day(line, fec_ini)
                if valid:
                    num_session += 1
                    self._create_session_from_sale_line(
                        event, num_session, line, fec_ini)
            fec_ini = fec_ini + relativedelta(days=+1)

    def _create_session_from_sale_line(
            self, event, num_session, line, date):
        vals = self._prepare_session_data_from_sale_line(
            event, num_session, line, date)
        session = self.env['event.track'].create(vals)
        if line.service_project_task:
            session.tasks = [(4, line.service_project_task.id)]
            duration = sum(
                line.service_project_task.sessions.mapped('duration'))
            line.service_project_task.planned_hours = duration
        return session

    def _prepare_session_data_from_sale_line(
            self, event, num_session, line, date):
        event_obj = self.env['event.event']
        if line.performance:
            duration = (line.performance * line.product_uom_qty)
        else:
            duration = line.product_uom_qty
        utc_dt = event_obj._put_utc_format_date(date, 0.0)
        vals = {'name': (_('Session %s for %s') % (str(num_session),
                                                   line.product_id.name)),
                'event_id': event.id,
                'date': utc_dt,
                'duration': duration}
        return vals


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.multi
    def product_id_change_with_wh(
        self, pricelist, product, qty=0, uom=False, qty_uos=0, uos=False,
        name='', partner_id=False, lang=False, update_tax=True,
        date_order=False, packaging=False, fiscal_position=False, flag=False,
            warehouse_id=False, context=None):
        product_obj = self.env['product.product']
        res = super(SaleOrderLine, self).product_id_change_with_wh(
            pricelist, product, qty=qty, uom=uom, qty_uos=qty_uos, uos=uos,
            name=name, partner_id=partner_id, lang=lang, update_tax=update_tax,
            date_order=date_order, packaging=packaging,
            fiscal_position=fiscal_position, flag=flag,
            warehouse_id=warehouse_id, context=context)
        product = product_obj.browse(product)
        if product.recurring_service and (len(product.route_ids) == 0 or
           len(product.route_ids) > 1 or product.route_ids[0].id !=
           self.env.ref('procurement_service_project.route_serv_project').id):
            if res.get('warning') == {}:
                res['warning'].update({
                    'title': _('Error in recurring service product'),
                    'message': _('This product is a recurring service, But it'
                                 ' has NOT checked only the "Generate'
                                 ' procurement-task" option in their routes'
                                 ' defined, consequently, this product will'
                                 ' not create task in the event.')})
            else:
                res['warning']['title'] = (
                    res['warning'].get('title') + '. ' +
                    _('Error in recurring service product'))
                res['warning']['message'] = (
                    res['warning'].get('message') + '. ' +
                    _('This product is a recurring service, But it has NOT'
                      ' checked only the "Generate procurement-task" option in'
                      ' their routes defined, consequently, this product will'
                      ' not create task in the event.'))
        return res