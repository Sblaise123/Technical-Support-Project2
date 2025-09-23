from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from models import Ticket, SLATarget, Customer
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class SLAMonitor:
    '''Monitor and manage SLA compliance for support tickets'''
    
    def __init__(self):
        # Default SLA targets (in hours)
        self.default_sla_targets = {
            ('standard', 'low'): {'first_response': 24, 'resolution': 72},
            ('standard', 'medium'): {'first_response': 8, 'resolution': 24},
            ('standard', 'high'): {'first_response': 4, 'resolution': 12},
            ('standard', 'critical'): {'first_response': 1, 'resolution': 4},
            ('standard', 'emergency'): {'first_response': 0.5, 'resolution': 2},
            
            ('premium', 'low'): {'first_response': 12, 'resolution': 48},
            ('premium', 'medium'): {'first_response': 4, 'resolution': 12},
            ('premium', 'high'): {'first_response': 2, 'resolution': 8},
            ('premium', 'critical'): {'first_response': 0.5, 'resolution': 2},
            ('premium', 'emergency'): {'first_response': 0.25, 'resolution': 1},
            
            ('enterprise', 'low'): {'first_response': 8, 'resolution': 24},
            ('enterprise', 'medium'): {'first_response': 2, 'resolution': 8},
            ('enterprise', 'high'): {'first_response': 1, 'resolution': 4},
            ('enterprise', 'critical'): {'first_response': 0.25, 'resolution': 1},
            ('enterprise', 'emergency'): {'first_response': 0.1, 'resolution': 0.5},
        }
    
    def calculate_sla_targets(self, ticket: Ticket) -> Dict[str, datetime]:
        '''Calculate SLA target times for a ticket'''
        
        # Get customer tier
        customer_tier = ticket.customer.tier if ticket.customer else 'standard'
        
        # Get SLA targets for this tier and priority
        targets = self.default_sla_targets.get(
            (customer_tier, ticket.priority),
            self.default_sla_targets[('standard', 'medium')]
        )
        
        created_at = ticket.created_at
        
        # Calculate target times (excluding weekends for non-emergency tickets)
        first_response_due = self.add_business_hours(
            created_at, 
            targets['first_response'],
            include_weekends=(ticket.priority in ['critical', 'emergency'])
        )
        
        resolution_due = self.add_business_hours(
            created_at,
            targets['resolution'],
            include_weekends=(ticket.priority in ['critical', 'emergency'])
        )
        
        return {
            'first_response': first_response_due,
            'resolution': resolution_due
        }
    
    def add_business_hours(self, start_time: datetime, hours: float, include_weekends: bool = False) -> datetime:
        '''Add business hours to a datetime, optionally including weekends'''
        
        if include_weekends:
            # For critical/emergency tickets, work 24/7
            return start_time + timedelta(hours=hours)
        
        # Business hours: Monday-Friday, 9 AM - 6 PM (9 hours