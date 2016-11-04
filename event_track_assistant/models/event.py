# -*- coding: utf-8 -*-
# (c) 2016 Alfredo de la Fuente - AvanzOSC
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html
from openerp import models, fields, api, exceptions, _
from .._common import _convert_to_local_date, _convert_time_to_float,\
    _convert_to_utc_date
from dateutil.relativedelta import relativedelta
from datetime import datetime
from pytz import timezone, utc

str2datetime = fields.Datetime.from_string
str2date = fields.Date.from_string
datetime2str = fields.Datetime.to_string
date2str = fields.Date.to_string


class EventEvent(models.Model):
    _inherit = 'event.event'

    claim_ids = fields.One2many(
        comodel_name='crm.claim', inverse_name='event_id', string='Claims')

    @api.onchange('date_begin')
    def onchange_date_begin(self):
        self.ensure_one()
        res = {}
        if self.date_begin:
            tracks = self.track_ids.filtered(
                lambda x: x.date and x.date < self.date_begin)
            if tracks:
                track = min(tracks, key=lambda x: x.date)
                res = {'warning': {
                       'title': _('Error in date begin'),
                       'message':
                       (_('Session %s with lower date') % track.name)}}
                self.date_begin = track.date
        return res

    @api.onchange('date_end')
    def onchange_date_end(self):
        self.ensure_one()
        res = {}
        if self.date_end:
            tracks = self.track_ids.filtered(
                lambda x: x.date and x.date > self.date_end)
            if tracks:
                track = max(tracks, key=lambda x: x.date)
                res = {'warning': {
                       'title': _('Error in date end'),
                       'message':
                       (_('Session %s with greater date') % track.name)}}
                self.date_end = track.date
        return res

    def _convert_date_to_local_format(self, date):
        if not date:
            return False
        new_date = str2datetime(date) if isinstance(date, str) else date
        new_date = new_date.date()
        local_date = datetime(
            int(new_date.strftime("%Y")), int(new_date.strftime("%m")),
            int(new_date.strftime("%d")), tzinfo=utc).astimezone(
            timezone(self.env.user.tz)).replace(tzinfo=None)
        return local_date

    def _convert_date_to_local_format_with_hour(self, date):
        return _convert_to_local_date(date, tz=self.env.user.tz)

    def _put_utc_format_date(self, date, time=0.0):
        return _convert_to_utc_date(date, time=time, tz=self.env.user.tz)

    def _convert_times_to_float(self, date):
        return _convert_time_to_float(date, tz=self.env.user.tz)


class EventTrack(models.Model):
    _inherit = 'event.track'

    @api.depends('date', 'duration')
    def _compute_estimated_date_end(self):
        for track in self.filtered(lambda t: t.date and t.duration):
            new_date = str2datetime(track.date) +\
                relativedelta(hours=track.duration)
            track.estimated_date_end = new_date

    @api.depends('event_id', 'event_id.registration_ids')
    def _compute_allowed_partner_ids(self):
        for track in self:
            partners = track.mapped('event_id.registration_ids.partner_id')
            track.allowed_partner_ids = [(6, 0, partners.ids)]

    @api.depends('presences', 'presences.real_duration')
    def _compute_real_duration(self):
        for track in self:
            track.real_duration = sum(track.mapped('presences.real_duration'))

    @api.depends('date', 'real_duration')
    def _compute_real_date_end(self):
        for track in self.filtered(lambda t: t.date and t.real_duration):
            new_date = str2datetime(track.date) +\
                relativedelta(hours=track.real_duration)
            track.real_date_end = new_date

    @api.depends('date')
    def _compute_session_date(self):
        for track in self.filtered('date'):
            from_date = _convert_to_local_date(track.date, self.env.user.tz)
            track.session_date = from_date.date()

    @api.depends('estimated_date_end')
    def _compute_session_end_date(self):
        for track in self.filtered('estimated_date_end'):
            from_date = _convert_to_local_date(
                track.estimated_date_end, self.env.user.tz)
            track.session_end_date = from_date.date()

    @api.depends('presences')
    def _compute_num_presences(self):
        for track in self:
            track.lit_presences = _('Presences: ') + str(len(track.presences))

    estimated_date_end = fields.Datetime(
        string='Estimated date end', compute='_compute_estimated_date_end',
        store=True)
    allowed_partner_ids = fields.Many2many(
        comodel_name="res.partner", relation="rel_partner_event_track",
        column1="event_track_id", column2="partner_id", string="Partners",
        copy=False, compute='_compute_allowed_partner_ids', store=True)
    presences = fields.One2many(
        comodel_name='event.track.presence', inverse_name='session',
        string='Presences')
    duration = fields.Float(string='Estimated duration', digits=(12, 4))
    real_duration = fields.Float(
        compute='_compute_real_duration', string='Real duration', store=True)
    real_date_end = fields.Datetime(
        string='Real date end', compute='_compute_real_date_end',
        store=True)
    session_date = fields.Date(
        string='Session date', compute='_compute_session_date', store=True)
    session_end_date = fields.Date(
        string='Session end date', compute='_compute_session_end_date',
        store=True)
    lit_presences = fields.Char(
        string='Num. presences', compute='_compute_num_presences',
        store=True)
    claim_ids = fields.One2many(
        comodel_name='crm.claim', inverse_name='session_id', string='Claims')

    @api.constrains('date')
    def _check_session_date(self):
        tz = self.env.user.tz
        date_begin = _convert_to_local_date(self.event_id.date_begin, tz)
        session_date = str2datetime(self.session_date)\
            if self.session_date else False
        if session_date and session_date.date() < date_begin.date():
            raise exceptions.Warning(
                _('Session %s with date lower than the event start date')
                % self.name)
        date_end = _convert_to_local_date(self.event_id.date_end, tz)
        if session_date and session_date.date() > date_end.date():
            raise exceptions.Warning(
                _('Session %s with date greater than the event start date')
                % self.name)


class EventTrackPresence(models.Model):
    _name = 'event.track.presence'
    _description = 'Session assistants'

    @api.depends('session', 'session.allowed_partner_ids')
    def _compute_allowed_partner_ids(self):
        for presence in self:
            presence.allowed_partner_ids = (
                [(6, 0, presence.session.allowed_partner_ids.ids)])

    @api.depends('session_date', 'real_duration')
    def _compute_real_date_end(self):
        for presence in self.filtered('real_duration'):
            start_date = str2datetime(presence.session_date)
            end_date = start_date + relativedelta(
                hours=presence.real_duration)
            presence.real_date_end = end_date

    @api.depends('session_date', 'session_duration')
    def _calculate_estimated_daynightlight_hours(self):
        event_obj = self.env['event.event']
        for presence in self:
            presence.estimated_daylight_hours = 0
            presence.estimated_nightlight_hours = 0
            fec_ini = event_obj._put_utc_format_date(
                presence.session_date_without_hour, 6.0).strftime(
                '%Y-%m-%d %H:%M:%S')
            fec_fin = event_obj._put_utc_format_date(
                presence.session_date_without_hour, 22.0).strftime(
                '%Y-%m-%d %H:%M:%S')
            if (presence.session_date_without_hour ==
                    presence.session_end_date_without_hour):
                self._calculate_daynightlightt_hours_same_day(
                    presence, fec_ini, fec_fin)
            else:
                self._calculate_daynightlightt_hours_in_distincts_days(
                    presence, fec_ini, fec_fin)

    @api.depends('real_date_end')
    def _calculate_real_daynightlight_hours(self):
        event_obj = self.env['event.event']
        for presence in self:
            presence.real_daylight_hours = 0
            presence.real_nightlight_hours = 0
            if presence.real_date_end:
                fec_ini = event_obj._put_utc_format_date(
                    presence.session_date_without_hour, 6.0).strftime(
                    '%Y-%m-%d %H:%M:%S')
                fec_fin = event_obj._put_utc_format_date(
                    presence.session_date_without_hour, 22.0).strftime(
                    '%Y-%m-%d %H:%M:%S')
                if (presence.session_date_without_hour ==
                        presence.session_end_date_without_hour):
                    self._calculate_real_daynightlightt_hours_same_day(
                        presence, fec_ini, fec_fin)
                else:
                    self._calculate_real_daynightlightt_hours_in_distinct_days(
                        presence, fec_ini, fec_fin)

    name = fields.Char(
        string='Partner', related='partner.name', store=True)
    session = fields.Many2one(
        comodel_name='event.track', string='Session', ondelete='cascade')
    event = fields.Many2one(
        comodel_name='event.event', string='Event', store=True,
        related='session.event_id')
    allowed_partner_ids = fields.Many2many(
        comodel_name='res.partner', compute='_compute_allowed_partner_ids',
        string='Allowed partners')
    session_date = fields.Datetime(
        related='session.date', string='Session date', store=True)
    session_date_without_hour = fields.Date(
        string='Session date without hour', related='session.session_date',
        store=True)
    session_end_date_without_hour = fields.Date(
        string='Session end date without hour',
        related='session.session_end_date', store=True)
    session_duration = fields.Float(
        related='session.duration', string='Duration', store=True)
    partner = fields.Many2one(
        comodel_name='res.partner', string='Partner', required=True)
    real_duration = fields.Float(string='Real duration', default=0.0)
    estimated_date_end = fields.Datetime(
        string='Estimated date end', related='session.estimated_date_end',
        store=True)
    real_date_end = fields.Datetime(
        string='Real date end', compute='_compute_real_date_end', store=True)
    estimated_daylight_hours = fields.Float(
        string='Estimated daylight hours', default=0.0,
        compute='_calculate_estimated_daynightlight_hours', store=True)
    estimated_nightlight_hours = fields.Float(
        string='Estimated nightlight hours', default=0.0,
        compute='_calculate_estimated_daynightlight_hours', store=True)
    real_daylight_hours = fields.Float(
        string='Real daylight hours', default=0.0,
        compute='_calculate_real_daynightlight_hours', store=True)
    real_nightlight_hours = fields.Float(
        string='Real nightlight hours', default=0.0,
        compute='_calculate_real_daynightlight_hours', store=True)
    notes = fields.Text(string='Notes')
    state = fields.Selection(
        selection=[('pending', 'Pending'), ('completed', 'Completed'),
                   ('canceled', 'Canceled')], string="State",
        default='pending', required=True)

    @api.multi
    def button_completed(self):
        self.write({'state': 'completed'})

    @api.multi
    def button_canceled(self):
        self.write({'state': 'canceled'})

    def _calculate_daynightlightt_hours_same_day(
            self, presence, fec_ini, fec_fin):
        if (presence.session_date >= fec_ini and
                presence.estimated_date_end <= fec_fin):
            presence.estimated_daylight_hours = presence.session_duration
        elif ((presence.session_date < fec_ini and
               presence.estimated_date_end < fec_ini) or
              (presence.session_date > fec_fin and
                  presence.estimated_date_end > fec_fin)):
            presence.estimated_nightlight_hours = presence.session_duration
        elif (presence.session_date < fec_ini and presence.estimated_date_end >
              fec_ini and presence.estimated_date_end < fec_fin):
            hour = self._calculate_hour_between_dates(
                fec_ini, presence.session_date)
            presence.estimated_nightlight_hours = hour
            hour = self._calculate_hour_between_dates(
                presence.estimated_date_end, fec_ini)
            presence.estimated_daylight_hours = hour
        elif (presence.session_date > fec_ini and presence.estimated_date_end >
              fec_fin):
            hour = self._calculate_hour_between_dates(
                fec_fin, presence.session_date)
            presence.estimated_daylight_hours = hour
            hour = self._calculate_hour_between_dates(
                presence.estimated_date_end, fec_fin)
            presence.estimated_nightlight_hours = hour

    def _calculate_real_daynightlightt_hours_same_day(
            self, presence, fec_ini, fec_fin):
        if (presence.session_date >= fec_ini and
                presence.real_date_end <= fec_fin):
            presence.real_daylight_hours = presence.real_duration
        elif ((presence.session_date < fec_ini and
               presence.real_date_end < fec_ini) or
              (presence.session_date > fec_fin and
                  presence.real_date_end > fec_fin)):
            presence.real_nightlight_hours = presence.real_duration
        elif (presence.session_date < fec_ini and presence.real_date_end >
              fec_ini and presence.real_date_end < fec_fin):
            hour = self._calculate_hour_between_dates(
                fec_ini, presence.session_date)
            presence.real_nightlight_hours = hour
            hour = self._calculate_hour_between_dates(
                presence.real_date_end, fec_ini)
            presence.real_daylight_hours = hour
        elif (presence.session_date > fec_ini and presence.real_date_end >
              fec_fin):
            hour = self._calculate_hour_between_dates(
                fec_fin, presence.session_date)
            presence.real_daylight_hours = hour
            hour = self._calculate_hour_between_dates(
                presence.real_date_end, fec_fin)
            presence.real_nightlight_hours = hour

    def _calculate_daynightlightt_hours_in_distincts_days(
            self, presence, fec_ini, fec_fin):
        event_obj = self.env['event.event']
        fec_ini2 = (fields.Date.from_string(str(fec_ini)) +
                    (relativedelta(days=1)))
        fec_ini2 = event_obj._put_utc_format_date(
            fec_ini2, 6.0).strftime('%Y-%m-%d %H:%M:%S')
        if presence.session_date > fec_ini and presence.session_date < fec_fin:
            hour = self._calculate_hour_between_dates(
                fec_fin, presence.session_date)
            presence.estimated_daylight_hours = hour
            hour = self._calculate_hour_between_dates(
                presence.estimated_date_end, fec_fin)
            presence.estimated_nightlight_hours = hour
        elif (presence.session_date >= fec_fin and
              presence.estimated_date_end <= fec_ini2):
            hour = self._calculate_hour_between_dates(
                presence.estimated_date_end, presence.session_date)
            presence.estimated_nightlight_hours = hour
        elif (presence.session_date >= fec_fin and
              presence.estimated_date_end > fec_ini2):
            hour = self._calculate_hour_between_dates(
                fec_ini2, presence.session_date)
            presence.estimated_nightlight_hours = hour
            hour = self._calculate_hour_between_dates(
                presence.estimated_date_end, fec_ini2)

    def _calculate_real_daynightlightt_hours_in_distinct_days(
            self, presence, fec_ini, fec_fin):
        event_obj = self.env['event.event']
        fec_ini2 = (fields.Date.from_string(str(fec_ini)) +
                    (relativedelta(days=1)))
        fec_ini2 = event_obj._put_utc_format_date(
            fec_ini2, 6.0).strftime('%Y-%m-%d %H:%M:%S')
        if presence.session_date > fec_ini and presence.session_date < fec_fin:
            hour = self._calculate_hour_between_dates(
                fec_fin, presence.session_date)
            presence.real_daylight_hours = hour
            hour = self._calculate_hour_between_dates(
                presence.real_date_end, fec_fin)
            presence.real_nightlight_hours = hour
        elif (presence.session_date >= fec_fin and
              presence.real_date_end <= fec_ini2):
            hour = self._calculate_hour_between_dates(
                presence.real_date_end, presence.session_date)
            presence.real_nightlight_hours = hour
        elif (presence.session_date >= fec_fin and
              presence.real_date_end > fec_ini2):
            hour = self._calculate_hour_between_dates(
                fec_ini2, presence.session_date)
            presence.real_nightlight_hours = hour
            hour = self._calculate_hour_between_dates(
                presence.real_date_end, fec_ini2)

    def _calculate_hour_between_dates(self, to_date, from_date):
        if from_date > to_date:
            return 0.0
        hours = (fields.Datetime.from_string(to_date) -
                 fields.Datetime.from_string(from_date))
        time = str(hours).split(':')
        hour = float(time[0])
        minutes = float(time[1]) / 60 if float(time[1]) > 0.0 else 0.0
        seconds = float(time[2]) / 360 if float(time[2]) > 0.0 else 0.0
        return hour + minutes + seconds

    def _update_presence_duration(self, hours, state=False, notes=False):
        vals = {'real_duration': hours}
        if state:
            vals['state'] = state
        if notes:
            vals['notes'] = notes
        self.write(vals)


class EventRegistration(models.Model):
    _inherit = 'event.registration'

    date_start = fields.Datetime(string='Date start')
    date_end = fields.Datetime(string='Date end')
    state = fields.Selection(
        selection=[('draft', 'Unconfirmed'), ('cancel', 'Cancelled'),
                   ('open', 'Confirmed'), ('done', 'Finalized')])

    @api.onchange('partner_id')
    def _onchange_partner(self):
        super(EventRegistration, self)._onchange_partner()
        self.date_start = self.event_id.date_begin if self.partner_id else\
            False
        self.date_end = self.event_id.date_end if self.partner_id else False

    @api.multi
    @api.onchange('date_start')
    def _onchange_date_start(self):
        self.ensure_one()
        res = {}
        if self.date_start and self.date_start < self.event_id.date_begin:
            self.date_start = self.event_id.date_begin
            return {'warning': {
                    'title': _('Error in date start'),
                    'message':
                    (_('Date start of registration less than date begin of'
                       ' event'))}}
        if (self.date_start and self.date_end and
                self.date_start > self.date_end):
            self.date_start = self.event_id.date_begin
            return {'warning': {
                    'title': _('Error in date start'),
                    'message':
                    (_('Date start of registration greater than date end of'
                       ' event'))}}
        return res

    @api.multi
    @api.onchange('date_end')
    def _onchange_date_end(self):
        self.ensure_one()
        res = {}
        if self.date_end and self.date_end > self.event_id.date_end:
            self.date_end = self.event_id.date_end
            return {'warning': {
                    'title': _('Error in date end'),
                    'message':
                    (_('Date end of registration greater than date end of'
                       ' event'))}}
        if (self.date_end and self.date_start and
                self.date_end < self.date_start):
            self.date_end = self.event_id.date_end
            return {'warning': {
                    'title': _('Error in date end'),
                    'message':
                    (_('Date end of registration less than date start of'
                       ' event'))}}
        return res

    @api.multi
    def button_registration_open(self):
        self.ensure_one()
        wiz_obj = self.env['wiz.event.append.assistant']
        if self.date_start and self.date_end:
            registrations = self.event_id.registration_ids.filtered(
                lambda x: x.id != self.id and x.partner_id and x.date_start and
                x.date_end and x.state in ('done', 'open') and
                x.partner_id.id == self.partner_id.id and
                ((self.date_end >= x.date_start and
                  self.date_end <= x.date_end) or
                 (self.date_start <= x.date_end and self.date_start >=
                  x.date_start)))
            if registrations:
                raise exceptions.Warning(
                    _('You can not confirm this registration, because their'
                      ' dates overlap with another record of the same'
                      ' employee'))
        wiz = wiz_obj.create(self._prepare_wizard_registration_open_vals())
        context = self.env.context.copy()
        context.update({
            'active_id': self.event_id.id,
            'active_ids': self.event_id.ids,
            'active_model': 'event.event',
        })
        return {'name': _('Add Person To Session'),
                'type': 'ir.actions.act_window',
                'res_model': 'wiz.event.append.assistant',
                'view_type': 'form',
                'view_mode': 'form',
                'res_id': wiz.id,
                'target': 'new',
                'context': context}

    def _prepare_wizard_registration_open_vals(self):
        tz = self.env.user.tz
        min_from_date = _convert_to_local_date(self.event_id.date_begin, tz)
        max_to_date = _convert_to_local_date(self.event_id.date_end, tz)
        from_date = _convert_to_local_date(self.date_start, tz)\
            if self.date_start else min_from_date
        to_date = _convert_to_local_date(self.date_end, tz)\
            if self.date_end else max_to_date
        wiz_vals = {
            'registration': self.id,
            'partner': self.partner_id.id,
            'min_event': self.event_id.id,
            'max_event': self.event_id.id,
            'from_date': from_date.date,
            'min_from_date': min_from_date.date(),
            'to_date': to_date.date(),
            'max_to_date': max_to_date.date(),
        }
        return wiz_vals

    @api.multi
    def new_button_reg_cancel(self):
        self.ensure_one()
        wiz_obj = self.env['wiz.event.delete.assistant']
        wiz = wiz_obj.create(self._prepare_wizard_reg_cancel_vals())
        if wiz.from_date and wiz.to_date and wiz.partner:
            wiz.write({
                'past_sessions': False,
                'later_sessions': False,
                'message': '',
            })
        context = self.env.context.copy()
        context.update({
            'active_id': self.event_id.id,
            'active_ids': self.event_id.ids,
            'active_model': 'event.event',
        })
        return {
            'name': _('Delete Person From Event-Session'),
            'type': 'ir.actions.act_window',
            'res_model': 'wiz.event.delete.assistant',
            'view_type': 'form',
            'view_mode': 'form',
            'res_id': wiz.id,
            'target': 'new',
            'context': context,
        }

    def _prepare_wizard_reg_cancel_vals(self):
        tz = self.env.user.tz
        min_from_date = _convert_to_local_date(self.event_id.date_begin, tz)
        max_to_date = _convert_to_local_date(self.event_id.date_end, tz)
        from_date = _convert_to_local_date(self.date_start, tz)\
            if self.date_start else min_from_date
        to_date = _convert_to_local_date(self.date_end, tz)\
            if self.date_end else max_to_date
        wiz_vals = {
            'registration': self.id,
            'partner': self.partner_id.id,
            'min_event': self.event_id.id,
            'max_event': self.event_id.id,
            'from_date': from_date.date,
            'min_from_date': min_from_date.date(),
            'to_date': to_date.date(),
            'max_to_date': max_to_date.date(),
            'past_sessions': False,
            'later_sessions': False,
            'message': ''
        }
        if str(from_date) < fields.Date.context_today(self):
            wiz_vals['from_date'] = fields.Date.context_today(self)
        return wiz_vals

    @api.multi
    def unlink(self):
        if any(self.filtered(lambda r: r.state != 'draft')):
            raise exceptions.Warning(
                _('You can only delete registration in draft status'))
        return super(EventRegistration, self).unlink()
