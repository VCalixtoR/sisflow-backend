import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import os

smtp_server = None

def smtpStart():

  global smtp_server

  smtp_server = smtplib.SMTP(
    os.getenv('SMTP_HOST'),
    os.getenv('SMTP_PORT'))

  smtp_server.ehlo()
  smtp_server.starttls()

  smtp_server.login(
    os.getenv('SMTP_LOGIN'),
    os.getenv('SMTP_PASSWORD'))

  print('# Connection to SMTP successfull')

def smtp_working():

  global smtp_server
  
  try:
    status = smtp_server.noop()[0]
  except:  # smtplib.SMTPServerDisconnected
    status = -1

  if status == 250:
    return True
  return False

def smtpSend(mail_from, mail_to, mail_subject, mail_message):

  global smtp_server

  if not smtp_server:
    print("# smtp not started")
    return

  mail = MIMEMultipart()
  mail['From'] = mail_from
  mail['To'] = mail_to
  mail['Subject'] = mail_subject
  mail.attach(MIMEText(mail_message, 'html'))

  smtp_server.sendmail(
    mail_from,
    mail_to,
    mail.as_string())

  smtp_server.quit()

def sendSignNumber(userMail, number, includeInnerHtml = '',includeDebug=False):

  TmpStr = includeInnerHtml if includeDebug else ''
  html = f'''
    <!DOCTYPE html>
    <html>
    <body>

    <h1 style="color:blue;">Sisges</h1>
    {TmpStr}
    <p>Este é seu numero de cadastro: {number} </p>

    </body>
    </html>
  '''

  smtpSend(
    os.getenv('SMTP_LOGIN'), 
    userMail,
    'Confirmação de cadastro Sisges', 
    html
  )