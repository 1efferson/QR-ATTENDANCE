import ipaddress
from flask import request, current_app
from functools import wraps
from flask import jsonify

def ip_in_network(ip, network_cidr):
    """
    Check if an IP address belongs to a network range (CIDR notation)
    Supports both IPv4 and IPv6
    """
    try:
        ip_obj = ipaddress.ip_address(ip)
        network_obj = ipaddress.ip_network(network_cidr, strict=False)
        return ip_obj in network_obj
    except ValueError:
        # Invalid IP or network format
        return False

def is_ip_whitelisted(ip_address=None):
    """
    Check if an IP address is in any of the configured school networks
    """
    if ip_address is None:
        ip_address = request.remote_addr
    
    # Check bypass list first
    bypass_ips = current_app.config.get('IP_WHITELIST_BYPASS', [])
    if ip_address in bypass_ips:
        return True
    
    # If whitelisting is disabled, allow all
    if not current_app.config.get('ENABLE_IP_WHITELISTING', True):
        return True
    
    # Get school IP ranges from config
    ip_ranges = current_app.config.get('SCHOOL_IP_RANGES', [])
    
    # Remove empty strings
    ip_ranges = [r.strip() for r in ip_ranges if r.strip()]
    
    if not ip_ranges:
        # No ranges configured - warn and block access 
        print("WARNING: No IP ranges configured for whitelisting")
        return False  # Block access if no ranges are configured
    
    # Check if IP is in any of the allowed ranges
    for network_cidr in ip_ranges:
        if ip_in_network(ip_address, network_cidr):
            return True
    
    return False

def ip_whitelist_required(f):
    """
    Decorator to require IP whitelisting for a route
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_ip_whitelisted():
            # Log the blocked attempt
            print(f"Blocked request from non-whitelisted IP: {request.remote_addr}")
            
            # Check if it's an AJAX request (JSON response)
            if request.is_json or request.headers.get('Accept') == 'application/json':
                return jsonify({
                    'success': False,
                    'message': 'Access denied: You must be on school premises to mark attendance'
                }), 403
            
            # For regular browser requests, show error page
            from flask import render_template
            return render_template('errors/ip_blocked.html'), 403
        
        return f(*args, **kwargs)
    return decorated_function

def get_client_ip():
    """
    Get real client IP address, handling proxies
    """
    # Check for proxy headers first
    if request.headers.get('X-Forwarded-For'):
        # X-Forwarded-For can contain multiple IPs: client, proxy1, proxy2
        # Take the first one which should be the client
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    
    # Fall back to remote_addr
    return request.remote_addr