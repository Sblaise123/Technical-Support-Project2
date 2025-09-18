MONITOR_SERVICE = """
import asyncio
import psutil
import ping3
import subprocess
import requests
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
import logging
import json

from database import SessionLocal
from models import Server, Service, HealthCheck, PerformanceMetric, Alert

logger = logging.getLogger(__name__)

class MonitorService:
    '''Core system monitoring service with automated checks'''
    
    def __init__(self):
        self.monitoring_active = False
        self.check_intervals = {
            'health_check': 60,      # Every minute
            'performance': 300,      # Every 5 minutes
            'service_check': 120,    # Every 2 minutes
            'network_check': 180     # Every 3 minutes
        }
        self.websocket_clients = {}
        self.alert_thresholds = {
            'cpu_critical': 90,
            'cpu_warning': 80,
            'memory_critical': 95,
            'memory_warning': 85,
            'disk_critical': 95,
            'disk_warning': 90,
            'response_time_critical': 5000,  # 5 seconds
            'response_time_warning': 2000    # 2 seconds
        }
    
    async def start_monitoring(self):
        '''Start all monitoring tasks'''
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        logger.info("Starting system monitoring...")
        
        # Start monitoring tasks
        asyncio.create_task(self.health_check_loop())
        asyncio.create_task(self.performance_monitoring_loop())
        asyncio.create_task(self.service_monitoring_loop())
        asyncio.create_task(self.network_monitoring_loop())
        
        logger.info("All monitoring tasks started")
    
    async def health_check_loop(self):
        '''Continuous health checking for all monitored servers'''
        while self.monitoring_active:
            try:
                db = SessionLocal()
                servers = db.query(Server).filter(
                    Server.monitoring_enabled == True
                ).all()
                
                for server in servers:
                    try:
                        health_data = await self.run_health_check(server)
                        await self.store_health_check(server.id, health_data, db)
                        await self.check_health_thresholds(server, health_data, db)
                        
                        # Send real-time updates to WebSocket clients
                        await self.broadcast_health_update(server.id, health_data)
                        
                    except Exception as e:
                        logger.error(f"Health check failed for server {server.hostname}: {e}")
                        await self.create_alert(
                            server.id,
                            'critical',
                            f"Health check failed: {str(e)}",
                            db
                        )
                
                db.close()
                await asyncio.sleep(self.check_intervals['health_check'])
                
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(60)
    
    async def run_health_check(self, server: Server) -> Dict:
        '''Run comprehensive health check for a server'''
        
        health_data = {
            'server_id': server.id,
            'hostname': server.hostname,
            'timestamp': datetime.utcnow().isoformat(),
            'checks': {}
        }
        
        try:
            # Ping test
            ping_time = ping3.ping(server.ip_address, timeout=5)
            health_data['checks']['ping'] = {
                'status': 'up' if ping_time else 'down',
                'response_time': ping_time * 1000 if ping_time else None
            }
            
            if server.hostname == 'localhost' or server.ip_address in ['127.0.0.1', 'localhost']:
                # Local server - get detailed metrics
                health_data.update(await self.get_local_server_metrics())
            else:
                # Remote server - use SSH or API
                health_data.update(await self.get_remote_server_metrics(server))
            
            # Overall health assessment
            health_data['overall_status'] = self.assess_overall_health(health_data)
            
        except Exception as e:
            logger.error(f"Health check error for {server.hostname}: {e}")
            health_data['checks']['error'] = str(e)
            health_data['overall_status'] = 'unhealthy'
        
        return health_data
    
    async def get_local_server_metrics(self) -> Dict:
        '''Get detailed metrics for local server'''
        
        metrics = {}
        
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            metrics['cpu_usage'] = cpu_percent
            
            # Memory usage
            memory = psutil.virtual_memory()
            metrics['memory_usage'] = memory.percent
            metrics['memory_available'] = memory.available / (1024**3)  # GB
            
            # Disk usage
            disk = psutil.disk_usage('/')
            metrics['disk_usage'] = (disk.used / disk.total) * 100
            metrics['disk_free'] = disk.free / (1024**3)  # GB
            
            # Network I/O
            network = psutil.net_io_counters()
            metrics['network_bytes_sent'] = network.bytes_sent
            metrics['network_bytes_recv'] = network.bytes_recv
            
            # System uptime
            uptime_seconds = datetime.now().timestamp() - psutil.boot_time()
            metrics['uptime'] = uptime_seconds / 3600  # hours
            
            # Load average (Linux/Unix)
            try:
                load_avg = psutil.getloadavg()
                metrics['load_average'] = {
                    '1min': load_avg[0],
                    '5min': load_avg[1],
                    '15min': load_avg[2]
                }
            except AttributeError:
                # Windows doesn't have load average
                pass
            
            # Process count
            metrics['process_count'] = len(psutil.pids())
            
            # Temperature (if available)
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    cpu_temp = list(temps.values())[0][0].current
                    metrics['cpu_temperature'] = cpu_temp
            except (AttributeError, IndexError):
                pass
            
        except Exception as e:
            logger.error(f"Error getting local server metrics: {e}")
            metrics['error'] = str(e)
        
        return metrics
    
    async def get_remote_server_metrics(self, server: Server) -> Dict:
        '''Get metrics for remote server via SSH or API'''
        
        metrics = {}
        
        try:
            # For demonstration, using basic ping and port checks
            # In production, this would use SSH, SNMP, or custom agents
            
            # Port connectivity checks
            common_ports = [22, 80, 443, 3306, 5432]  # SSH, HTTP, HTTPS, MySQL, PostgreSQL
            metrics['port_checks'] = {}
            
            for port in common_ports:
                try:
                    import socket
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    result = sock.connect_ex((server.ip_address, port))
                    metrics['port_checks'][f'port_{port}'] = 'open' if result == 0 else 'closed'
                    sock.close()
                except Exception as e:
                    metrics['port_checks'][f'port_{port}'] = f'error: {e}'
            
            # HTTP endpoint check if it's a web server
            if server.server_type in ['web', 'api', 'application']:
                try:
                    response = requests.get(f'http://{server.ip_address}', timeout=10)
                    metrics['http_check'] = {
                        'status_code': response.status_code,
                        'response_time': response.elapsed.total_seconds() * 1000,
                        'status': 'healthy' if response.status_code == 200 else 'unhealthy'
                    }
                except requests.RequestException as e:
                    metrics['http_check'] = {
                        'status': 'error',
                        'error': str(e)
                    }
            
            # DNS resolution check
            try:
                import socket
                socket.gethostbyname(server.hostname)
                metrics['dns_resolution'] = 'success'
            except socket.gaierror:
                metrics['dns_resolution'] = 'failed'
            
        except Exception as e:
            logger.error(f"Error getting remote server metrics for {server.hostname}: {e}")
            metrics['error'] = str(e)
        
        return metrics
    
    def assess_overall_health(self, health_data: Dict) -> str:
        '''Assess overall server health based on all metrics'''
        
        # Check ping status
        ping_status = health_data.get('checks', {}).get('ping', {}).get('status')
        if ping_status == 'down':
            return 'critical'
        
        # Check critical thresholds
        cpu_usage = health_data.get('cpu_usage', 0)
        memory_usage = health_data.get('memory_usage', 0)
        disk_usage = health_data.get('disk_usage', 0)
        
        if (cpu_usage > self.alert_thresholds['cpu_critical'] or 
            memory_usage > self.alert_thresholds['memory_critical'] or 
            disk_usage > self.alert_thresholds['disk_critical']):
            return 'critical'
        
        # Check warning thresholds
        if (cpu_usage > self.alert_thresholds['cpu_warning'] or 
            memory_usage > self.alert_thresholds['memory_warning'] or 
            disk_usage > self.alert_thresholds['disk_warning']):
            return 'warning'
        
        # Check HTTP response if available
        http_check = health_data.get('http_check', {})
        if http_check.get('status') == 'error':
            return 'warning'
        
        return 'healthy'
    
    async def performance_monitoring_loop(self):
        '''Monitor and store performance metrics'''
        while self.monitoring_active:
            try:
                db = SessionLocal()
                servers = db.query(Server).filter(
                    Server.monitoring_enabled == True
                ).all()
                
                for server in servers:
                    try:
                        perf_metrics = await self.collect_performance_metrics(server)
                        await self.store_performance_metrics(server.id, perf_metrics, db)
                        
                    except Exception as e:
                        logger.error(f"Performance monitoring failed for {server.hostname}: {e}")
                
                db.close()
                await asyncio.sleep(self.check_intervals['performance'])
                
            except Exception as e:
                logger.error(f"Performance monitoring loop error: {e}")
                await asyncio.sleep(300)
    
    async def collect_performance_metrics(self, server: Server) -> Dict:
        '''Collect detailed performance metrics'''
        
        if server.hostname == 'localhost' or server.ip_address in ['127.0.0.1', 'localhost']:
            return await self.get_local_performance_metrics()
        else:
            return await self.get_remote_performance_metrics(server)
    
    async def get_local_performance_metrics(self) -> Dict:
        '''Get detailed local performance metrics'''
        
        metrics = {
            'timestamp': datetime.utcnow(),
            'cpu_usage': psutil.cpu_percent(interval=1),
            'memory_usage': psutil.virtual_memory().percent,
            'disk_usage': psutil.disk_usage('/').percent,
            'network_io': psutil.net_io_counters()._asdict(),
            'disk_io': psutil.disk_io_counters()._asdict() if psutil.disk_io_counters() else {},
            'cpu_freq': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
            'cpu_count': psutil.cpu_count()
        }
        
        # Calculate response time (simulate application response)
        import time
        start_time = time.time()
        # Simulate some work
        await asyncio.sleep(0.001)
        metrics['response_time'] = (time.time() - start_time) * 1000  # ms
        
        return metrics
    
    async def service_monitoring_loop(self):
        '''Monitor individual services and applications'''
        while self.monitoring_active:
            try:
                db = SessionLocal()
                services = db.query(Service).filter(
                    Service.monitoring_enabled == True
                ).all()
                
                for service in services:
                    try:
                        service_status = await self.check_service_status(service)
                        await self.update_service_status(service, service_status, db)
                        
                    except Exception as e:
                        logger.error(f"Service monitoring failed for {service.name}: {e}")
                
                db.close()
                await asyncio.sleep(self.check_intervals['service_check'])
                
            except Exception as e:
                logger.error(f"Service monitoring loop error: {e}")
                await asyncio.sleep(120)
    
    async def check_service_status(self, service: Service) -> Dict:
        '''Check status of a specific service'''
        
        status_data = {
            'service_id': service.id,
            'name': service.name,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        try:
            if service.service_type == 'http':
                # HTTP/HTTPS service check
                response = requests.get(service.endpoint_url, timeout=10)
                status_data.update({
                    'status': 'available' if response.status_code == 200 else 'degraded',
                    'response_time': response.elapsed.total_seconds() * 1000,
                    'status_code': response.status_code,
                    'response_size': len(response.content)
                })
                
            elif service.service_type == 'database':
                # Database connection check
                status_data.update(await self.check_database_service(service))
                
            elif service.service_type == 'tcp':
                # TCP port check
                status_data.update(await self.check_tcp_service(service))
                
            else:
                # Generic service check
                status_data.update(await self.check_generic_service(service))
                
        except Exception as e:
            status_data.update({
                'status': 'unavailable',
                'error': str(e)
            })
        
        return status_data
    
    async def check_database_service(self, service: Service) -> Dict:
        '''Check database service connectivity'''
        
        try:
            if 'mysql' in service.endpoint_url.lower():
                # MySQL check
                import pymysql
                connection = pymysql.connect(
                    host=service.host,
                    port=service.port,
                    user=service.username,
                    password=service.password,
                    database=service.database_name,
                    connect_timeout=10
                )
                
                start_time = time.time()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                response_time = (time.time() - start_time) * 1000
                
                connection.close()
                
                return {
                    'status': 'available',
                    'response_time': response_time,
                    'connection_test': 'passed'
                }
                
            # Add other database types as needed
            
        except Exception as e:
            return {
                'status': 'unavailable',
                'error': str(e),
                'connection_test': 'failed'
            }
    
    async def network_monitoring_loop(self):
        '''Monitor network connectivity and performance'''
        while self.monitoring_active:
            try:
                # Network performance tests
                await self.run_network_tests()
                await asyncio.sleep(self.check_intervals['network_check'])
                
            except Exception as e:
                logger.error(f"Network monitoring error: {e}")
                await asyncio.sleep(180)
    
    async def run_network_tests(self):
        '''Run comprehensive network performance tests'''
        
        # Test external connectivity
        external_hosts = ['8.8.8.8', 'cloudflare.com', 'google.com']
        
        for host in external_hosts:
            try:
                ping_time = ping3.ping(host, timeout=5)
                logger.info(f"Ping to {host}: {ping_time * 1000:.2f}ms" if ping_time else f"Ping to {host}: timeout")
                
            except Exception as e:
                logger.error(f"Network test to {host} failed: {e}")
    
    # WebSocket methods for real-time updates
    def add_websocket_client(self, client_id: str, websocket):
        '''Add WebSocket client for real-time updates'''
        self.websocket_clients[client_id] = websocket
        logger.info(f"WebSocket client {client_id} connected for monitoring updates")
    
    def remove_websocket_client(self, client_id: str):
        '''Remove WebSocket client'''
        if client_id in self.websocket_clients:
            del self.websocket_clients[client_id]
            logger.info(f"WebSocket client {client_id} disconnected")
    
    async def broadcast_health_update(self, server_id: int, health_data: Dict):
        '''Broadcast health updates to all connected WebSocket clients'''
        
        if not self.websocket_clients:
            return
        
        update_message = {
            'type': 'health_update',
            'server_id': server_id,
            'data': health_data,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        disconnected_clients = []
        
        for client_id, websocket in self.websocket_clients.items():
            try:
                await websocket.send_text(json.dumps(update_message))
            except Exception as e:
                logger.error(f"Failed to send update to client {client_id}: {e}")
                disconnected_clients.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected_clients:
            self.remove_websocket_client(client_id)
    
    # Alert and threshold checking
    async def check_health_thresholds(self, server: Server, health_data: Dict, db: Session):
        '''Check if health metrics exceed alert thresholds'''
        
        alerts_to_create = []
        
        # CPU threshold check
        cpu_usage = health_data.get('cpu_usage', 0)
        if cpu_usage > self.alert_thresholds['cpu_critical']:
            alerts_to_create.append({
                'severity': 'critical',
                'message': f'CPU usage critical: {cpu_usage:.1f}%',
                'metric': 'cpu_usage',
                'value': cpu_usage
            })
        elif cpu_usage > self.alert_thresholds['cpu_warning']:
            alerts_to_create.append({
                'severity': 'warning',
                'message': f'CPU usage high: {cpu_usage:.1f}%',
                'metric': 'cpu_usage',
                'value': cpu_usage
            })
        
        # Memory threshold check
        memory_usage = health_data.get('memory_usage', 0)
        if memory_usage > self.alert_thresholds['memory_critical']:
            alerts_to_create.append({
                'severity': 'critical',
                'message': f'Memory usage critical: {memory_usage:.1f}%',
                'metric': 'memory_usage',
                'value': memory_usage
            })
        elif memory_usage > self.alert_thresholds['memory_warning']:
            alerts_to_create.append({
                'severity': 'warning',
                'message': f'Memory usage high: {memory_usage:.1f}%',
                'metric': 'memory_usage',
                'value': memory_usage
            })
        
        # Disk threshold check
        disk_usage = health_data.get('disk_usage', 0)
        if disk_usage > self.alert_thresholds['disk_critical']:
            alerts_to_create.append({
                'severity': 'critical',
                'message': f'Disk usage critical: {disk_usage:.1f}%',
                'metric': 'disk_usage',
                'value': disk_usage
            })
        elif disk_usage > self.alert_thresholds['disk_warning']:
            alerts_to_create.append({
                'severity': 'warning',
                'message': f'Disk usage high: {disk_usage:.1f}%',
                'metric': 'disk_usage',
                'value': disk_usage
            })
        
        # Create alerts
        for alert_data in alerts_to_create:
            await self.create_alert(
                server.id,
                alert_data['severity'],
                alert_data['message'],
                db,
                metric=alert_data['metric'],
                value=alert_data['value']
            )
    
    async def create_alert(self, server_id: int, severity: str, message: str, db: Session, **kwargs):
        '''Create new alert with deduplication'''
        
        # Check for existing similar alerts to avoid spam
        existing_alert = db.query(Alert).filter(
            Alert.server_id == server_id,
            Alert.message == message,
            Alert.status == 'active',
            Alert.created_at >= datetime.utcnow() - timedelta(minutes=10)
        ).first()
        
        if existing_alert:
            # Update existing alert count instead of creating new one
            existing_alert.count += 1
            existing_alert.updated_at = datetime.utcnow()
            db.commit()
            return existing_alert
        
        # Create new alert
        new_alert = Alert(
            server_id=server_id,
            severity=severity,
            message=message,
            status='active',
            metric=kwargs.get('metric'),
            value=kwargs.get('value'),
            count=1,
            created_at=datetime.utcnow()
        )
        
        db.add(new_alert)
        db.commit()
        db.refresh(new_alert)
        
        logger.warning(f"Alert created: {severity.upper()} - {message}")
        
        return new_alert
    
    # Storage methods
    async def store_health_check(self, server_id: int, health_data: Dict, db: Session):
        '''Store health check results'''
        
        health_check = HealthCheck(
            server_id=server_id,
            cpu_usage=health_data.get('cpu_usage'),
            memory_usage=health_data.get('memory_usage'),
            disk_usage=health_data.get('disk_usage'),
            network_latency=health_data.get('checks', {}).get('ping', {}).get('response_time'),
            uptime=health_data.get('uptime'),
            status=health_data.get('overall_status', 'unknown'),
            raw_data=health_data,
            checked_at=datetime.utcnow()
        )
        
        db.add(health_check)
        db.commit()
    
    async def store_performance_metrics(self, server_id: int, metrics: Dict, db: Session):
        '''Store performance metrics'''
        
        performance_metric = PerformanceMetric(
            server_id=server_id,
            timestamp=metrics['timestamp'],
            cpu_usage=metrics.get('cpu_usage'),
            memory_usage=metrics.get('memory_usage'),
            disk_usage=metrics.get('disk_usage'),
            network_io=metrics.get('network_io', {}).get('bytes_sent', 0) + 
                      metrics.get('network_io', {}).get('bytes_recv', 0),
            response_time=metrics.get('response_time'),
            raw_metrics=metrics
        )
        
                db.add(performance_metric)
                db.commit()
        
        """
