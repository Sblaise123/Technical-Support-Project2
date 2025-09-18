from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import asyncio
import logging
from typing import List, Dict, Optional

from database import engine, Base, get_db
from models import (
    Server, Service, Incident, Alert, HealthCheck, 
    PerformanceMetric, MaintenanceWindow
)
from schemas import (
    ServerCreate, ServiceCreate, IncidentResponse, 
    AlertResponse, HealthCheckResponse
)
from services.monitor_service import MonitorService
from services.alert_manager import AlertManager
from services.incident_manager import IncidentManager
from services.diagnostic_service import DiagnosticService
from services.notification_service import NotificationService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="System Monitor Pro - Incident Response Platform",
    description="Comprehensive system monitoring with automated incident response",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
monitor_service = MonitorService()
alert_manager = AlertManager()
incident_manager = IncidentManager()
diagnostic_service = DiagnosticService()
notification_service = NotificationService()

@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    
    # Start background monitoring tasks
    asyncio.create_task(monitor_service.start_monitoring())
    asyncio.create_task(alert_manager.start_alert_processing())
    
    logger.info("System Monitor Pro started successfully")

@app.post("/api/servers/", response_model=dict)
async def register_server(
    server: ServerCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    '''Register a new server for monitoring'''
    
    db_server = Server(
        hostname=server.hostname,
        ip_address=server.ip_address,
        server_type=server.server_type,
        environment=server.environment,
        location=server.location,
        monitoring_enabled=True,
        created_at=datetime.utcnow()
    )
    
    db.add(db_server)
    db.commit()
    db.refresh(db_server)
    
    # Start monitoring this server
    background_tasks.add_task(monitor_service.add_server_monitoring, db_server.id)
    
    # Run initial health check
    background_tasks.add_task(run_initial_server_check, db_server.id)
    
    logger.info(f"Server {server.hostname} registered for monitoring")
    
    return {
        "message": "Server registered successfully",
        "server_id": db_server.id,
        "monitoring_started": True
    }

@app.get("/api/dashboard/overview")
async def get_monitoring_overview(db: Session = Depends(get_db)):
    '''Get comprehensive system monitoring overview'''
    
    # Get current system status
    total_servers = db.query(Server).filter(Server.monitoring_enabled == True).count()
    healthy_servers = db.query(Server).filter(
        Server.status == 'healthy',
        Server.monitoring_enabled == True
    ).count()
    
    # Get active incidents
    active_incidents = db.query(Incident).filter(
        Incident.status.in_(['investigating', 'identified', 'monitoring'])
    ).count()
    
    # Get recent alerts
    recent_alerts = db.query(Alert).filter(
        Alert.created_at >= datetime.utcnow() - timedelta(hours=24),
        Alert.severity.in_(['critical', 'warning'])
    ).count()
    
    # Get service availability
    services_status = db.query(Service).filter(Service.monitoring_enabled == True).all()
    available_services = sum(1 for s in services_status if s.status == 'available')
    
    # Calculate overall system health
    system_health = calculate_system_health(db)
    
    return {
        "system_health": system_health,
        "servers": {
            "total": total_servers,
            "healthy": healthy_servers,
            "unhealthy": total_servers - healthy_servers,
            "health_percentage": (healthy_servers / total_servers * 100) if total_servers > 0 else 0
        },
        "services": {
            "total": len(services_status),
            "available": available_services,
            "unavailable": len(services_status) - available_services,
            "availability_percentage": (available_services / len(services_status) * 100) if services_status else 0
        },
        "incidents": {
            "active": active_incidents,
            "resolved_24h": get_resolved_incidents_24h(db)
        },
        "alerts": {
            "recent_24h": recent_alerts,
            "critical_active": get_active_critical_alerts(db)
        }
    }

@app.get("/api/servers/{server_id}/health", response_model=HealthCheckResponse)
async def get_server_health(
    server_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    '''Get detailed health information for a specific server'''
    
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    # Run real-time health check
    health_data = await monitor_service.run_health_check(server)
    
    # Store health check results
    db_health_check = HealthCheck(
        server_id=server_id,
        cpu_usage=health_data['cpu_usage'],
        memory_usage=health_data['memory_usage'],
        disk_usage=health_data['disk_usage'],
        network_latency=health_data['network_latency'],
        uptime=health_data['uptime'],
        status=health_data['overall_status'],
        checked_at=datetime.utcnow()
    )
    
    db.add(db_health_check)
    db.commit()
    
    # Check if alerts need to be triggered
    background_tasks.add_task(alert_manager.process_health_check, health_data, server_id)
    
    return health_data

@app.post("/api/incidents/", response_model=IncidentResponse)
async def create_incident(
    title: str,
    description: str,
    severity: str,
    affected_services: List[str],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    '''Create new incident and initiate response procedures'''
    
    # Create incident
    db_incident = Incident(
        title=title,
        description=description,
        severity=severity,
        status='investigating',
        affected_services=affected_services,
        created_at=datetime.utcnow(),
        created_by='system'  # In production, this would be current user
    )
    
    db.add(db_incident)
    db.commit()
    db.refresh(db_incident)
    
    # Start incident response procedures
    background_tasks.add_task(incident_manager.initiate_response, db_incident.id)
    
    # Send notifications
    background_tasks.add_task(
        notification_service.send_incident_notification,
        db_incident.id,
        'created'
    )
    
    # Run automated diagnostics
    background_tasks.add_task(
        diagnostic_service.run_incident_diagnostics,
        db_incident.id
    )
    
    logger.critical(f"Incident #{db_incident.id} created: {title}")
    
    return db_incident

@app.put("/api/incidents/{incident_id}/status")
async def update_incident_status(
    incident_id: int,
    status: str,
    update_message: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    '''Update incident status with communication to stakeholders'''
    
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    old_status = incident.status
    incident.status = status
    incident.updated_at = datetime.utcnow()
    
    # Add status update to incident timeline
    incident_manager.add_status_update(incident_id, status, update_message, db)
    
    # If resolved, record resolution time
    if status == 'resolved':
        incident.resolved_at = datetime.utcnow()
        incident.resolution_time = (incident.resolved_at - incident.created_at).total_seconds() / 60  # minutes
    
    db.commit()
    
    # Send status update notifications
    background_tasks.add_task(
        notification_service.send_status_update,
        incident_id,
        old_status,
        status,
        update_message
    )
    
    # Update service status pages
    background_tasks.add_task(
        update_status_page,
        incident_id,
        status
    )
    
    return {"message": f"Incident status updated to {status}"}

@app.get("/api/performance/metrics/{server_id}")
async def get_performance_metrics(
    server_id: int,
    hours: int = 24,
    db: Session = Depends(get_db)
):
    '''Get historical performance metrics for analysis'''
    
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)
    
    metrics = db.query(PerformanceMetric).filter(
        PerformanceMetric.server_id == server_id,
        PerformanceMetric.timestamp >= start_time,
        PerformanceMetric.timestamp <= end_time
    ).order_by(PerformanceMetric.timestamp).all()
    
    # Process metrics for visualization
    processed_metrics = {
        'timestamps': [m.timestamp.isoformat() for m in metrics],
        'cpu_usage': [m.cpu_usage for m in metrics],
        'memory_usage': [m.memory_usage for m in metrics],
        'disk_usage': [m.disk_usage for m in metrics],
        'network_io': [m.network_io for m in metrics],
        'response_time': [m.response_time for m in metrics]
    }
    
    # Calculate statistics
    if metrics:
        cpu_values = [m.cpu_usage for m in metrics if m.cpu_usage is not None]
        memory_values = [m.memory_usage for m in metrics if m.memory_usage is not None]
        
        statistics = {
            'cpu': {
                'avg': sum(cpu_values) / len(cpu_values) if cpu_values else 0,
                'max': max(cpu_values) if cpu_values else 0,
                'min': min(cpu_values) if cpu_values else 0
            },
            'memory': {
                'avg': sum(memory_values) / len(memory_values) if memory_values else 0,
                'max': max(memory_values) if memory_values else 0,
                'min': min(memory_values) if memory_values else 0
            }
        }
    else:
        statistics = {'cpu': {'avg': 0, 'max': 0, 'min': 0}, 'memory': {'avg': 0, 'max': 0, 'min': 0}}
    
    return {
        'server_id': server_id,
        'period_hours': hours,
        'metrics': processed_metrics,
        'statistics': statistics,
        'data_points': len(metrics)
    }

@app.post("/api/maintenance/schedule")
async def schedule_maintenance(
    server_ids: List[int],
    start_time: str,
    end_time: str,
    description: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    '''Schedule maintenance window with automatic monitoring adjustments'''
    
    maintenance_window = MaintenanceWindow(
        server_ids=server_ids,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
        description=description,
        status='scheduled',
        created_at=datetime.utcnow()
    )
    
    db.add(maintenance_window)
    db.commit()
    db.refresh(maintenance_window)
    
    # Schedule monitoring adjustments
    background_tasks.add_task(
        monitor_service.schedule_maintenance_mode,
        maintenance_window.id
    )
    
    # Send maintenance notifications
    background_tasks.add_task(
        notification_service.send_maintenance_notification,
        maintenance_window.id
    )
    
    return {
        "message": "Maintenance window scheduled",
        "maintenance_id": maintenance_window.id,
        "affected_servers": len(server_ids)
    }

@app.get("/api/reports/incident-summary")
async def get_incident_summary_report(
    days: int = 30,
    db: Session = Depends(get_db)
):
    '''Generate comprehensive incident summary report'''
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    incidents = db.query(Incident).filter(
        Incident.created_at >= start_date
    ).all()
    
    # Calculate metrics
    total_incidents = len(incidents)
    resolved_incidents = len([i for i in incidents if i.status == 'resolved'])
    avg_resolution_time = 0
    
    if resolved_incidents > 0:
        resolution_times = [
            i.resolution_time for i in incidents 
            if i.resolution_time is not None
        ]
        if resolution_times:
            avg_resolution_time = sum(resolution_times) / len(resolution_times)
    
    # Severity breakdown
    severity_breakdown = {}
    for severity in ['low', 'medium', 'high', 'critical']:
        severity_breakdown[severity] = len([
            i for i in incidents if i.severity == severity
        ])
    
    # Service impact analysis
    affected_services = {}
    for incident in incidents:
        for service in incident.affected_services or []:
            affected_services[service] = affected_services.get(service, 0) + 1
    
    # MTTR (Mean Time To Resolution) by severity
    mttr_by_severity = {}
    for severity in ['low', 'medium', 'high', 'critical']:
        severity_incidents = [
            i for i in incidents 
            if i.severity == severity and i.resolution_time is not None
        ]
        if severity_incidents:
            mttr_by_severity[severity] = sum(
                i.resolution_time for i in severity_incidents
            ) / len(severity_incidents)
        else:
            mttr_by_severity[severity] = 0
    
    return {
        'report_period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'days': days
        },
        'summary': {
            'total_incidents': total_incidents,
            'resolved_incidents': resolved_incidents,
            'resolution_rate': (resolved_incidents / total_incidents * 100) if total_incidents > 0 else 0,
            'avg_resolution_time_minutes': round(avg_resolution_time, 2)
        },
        'severity_breakdown': severity_breakdown,
        'most_affected_services': dict(
            sorted(affected_services.items(), key=lambda x: x[1], reverse=True)[:5]
        ),
        'mttr_by_severity': mttr_by_severity
    }

# WebSocket endpoint for real-time monitoring updates
@app.websocket("/ws/monitoring/{client_id}")
async def monitoring_websocket(websocket: WebSocket, client_id: str):
    await websocket.accept()
    
    # Add client to monitoring updates
    monitor_service.add_websocket_client(client_id, websocket)
    
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()
            # Process any client requests for specific monitoring data
            await process_monitoring_request(data, websocket)
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
    finally:
        monitor_service.remove_websocket_client(client_id)

async def process_monitoring_request(data: str, websocket: WebSocket):
    '''Process real-time monitoring data requests'''
    try:
        import json
        request = json.loads(data)
        
        if request.get('type') == 'subscribe_server':
            server_id = request.get('server_id')
            # Send real-time updates for this server
            await websocket.send_text(json.dumps({
                'type': 'subscription_confirmed',
                'server_id': server_id
            }))
            
    except Exception as e:
        logger.error(f"Error processing monitoring request: {e}")

# Helper functions
def calculate_system_health(db: Session) -> str:
    '''Calculate overall system health status'''
    # This would implement complex health calculation logic
    # For now, return a simple calculation
    
    total_servers = db.query(Server).filter(Server.monitoring_enabled == True).count()
    healthy_servers = db.query(Server).filter(
        Server.status == 'healthy',
        Server.monitoring_enabled == True
    ).count()
    
    if total_servers == 0:
        return 'unknown'
    
    health_percentage = (healthy_servers / total_servers) * 100
    
    if health_percentage >= 95:
        return 'excellent'
    elif health_percentage >= 85:
        return 'good'
    elif health_percentage >= 70:
        return 'fair'
    else:
        return 'poor'

def get_resolved_incidents_24h(db: Session) -> int:
    '''Get count of incidents resolved in last 24 hours'''
    return db.query(Incident).filter(
        Incident.resolved_at >= datetime.utcnow() - timedelta(hours=24)
    ).count()

def get_active_critical_alerts(db: Session) -> int:
    '''Get count of active critical alerts'''
    return db.query(Alert).filter(
        Alert.severity == 'critical',
        Alert.status == 'active'
    ).count()

async def run_initial_server_check(server_id: int):
    '''Run initial health check for newly registered server'''
    # This would implement initial server validation
    pass

async def update_status_page(incident_id: int, status: str):
    '''Update public status page with incident information'''
    # This would integrate with status page services
    pass

