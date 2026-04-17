import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings
from django.template.loader import render_to_string
import threading
from django.db.models import Max
from .models import Profile
def send_brevo_email(to_email, subject, html_content=None, template_name=None, context=None):
    """
    Sends an email via Brevo API in a background thread.
    Can be called with raw html_content OR a template_name + context.
    """
    def run_send():
        # 1. Configuration
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.BREVO_API_KEY

        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )

        # 2. Handle Template Rendering if necessary
        # This allows you to pass a file like 'emm.html' directly
        if template_name and context:
            final_html = render_to_string(template_name, context)
        else:
            final_html = html_content

        # 3. Create the Email Object
        email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to_email}],
            sender={
                "email": "kevinmalasa2000@gmail.com", 
                "name": "Edoret Polytechnic Sacco"
            },
            subject=subject,
            html_content=final_html
        )

        # 4. Execute the Send
        try:
            api_instance.send_transac_email(email)
        except ApiException as e:
            print(f"Brevo API Error: {e}")

    # Start the thread so the web page doesn't wait/hang
    email_thread = threading.Thread(target=run_send)
    email_thread.start()


def generate_membership_number():
    last = Profile.objects.exclude(membership_number__isnull=True)\
                          .aggregate(Max('membership_number'))['membership_number__max']
    
    if last:
        return str(int(last) + 1)
    return "1"