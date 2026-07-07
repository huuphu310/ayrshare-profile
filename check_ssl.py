import ssl
import socket
from datetime import datetime
import certifi # Import the certifi library

def check_ssl_certificate(hostname):
    # Use the default context, but tell it to use certifi's trust store
    context = ssl.create_default_context(cafile=certifi.where())
    print(f"Checking certificate for {hostname} using an updated trust store...")

    try:
        with socket.create_connection((hostname, 443)) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                print("\n--- Verification Successful! ---")

                # Certificate Expiry
                expiry_date = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
                print(f"Certificate for {hostname} expires on: {expiry_date}")
                if expiry_date < datetime.now():
                    print("Warning: Certificate has expired.")

                # Subject Alternative Name
                sans = [san[1] for san in cert.get('subjectAltName', []) if san[0].lower() == 'dns']
                if hostname not in sans:
                    print(f"Warning: Hostname '{hostname}' not found in Subject Alternative Names: {sans}")

                # Issuer
                issuer = dict(x[0] for x in cert['issuer'])
                print(f"Certificate issued by: {issuer.get('commonName', 'N/A')}")

    except ssl.SSLCertVerificationError as e:
        print(f"\nSSL Certificate Verification Error: {e}")
        print("This might still happen if there is a proxy or firewall intercepting traffic.")
    except socket.gaierror as e:
        print(f"Could not resolve hostname {hostname}: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    check_ssl_certificate("ccreator.site")
