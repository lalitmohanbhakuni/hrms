from django import template
import calendar

register = template.Library()

@register.filter
def month_name(month_num):
    return calendar.month_name[int(month_num)]