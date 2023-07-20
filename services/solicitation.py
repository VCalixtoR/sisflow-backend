from datetime import datetime, timedelta
import json
import traceback
import threading

from flask import Flask, abort, request
from flask_restful import Resource, Api, reqparse

from utils.dbUtils import *
from utils.cryptoFunctions import isAuthTokenValid
from utils.eventScheduler import addTransitionToEventScheduler, removeEventFromScheduler, printEventSchedulerInfo
from utils.sistemConfig import getCoordinatorEmail
from utils.smtpMails import addToSmtpMailServer
from utils.utils import getFormatedMySQLJSON, sistemStrParser

from services.dynamicPage import getDynamicPage
from services.solicitationTransitions import getTransitions

def sendSolicitationMails(solicitationId, studentData):
  
  try:
    solicitationMails = dbGetAll(
      " SELECT dm.mail_subject, dm.mail_body_html, dm.is_sent_to_student, dm.is_sent_to_advisor, dm.is_sent_to_coordinator "
      "   FROM solicitation AS s "
      "     JOIN solicitation_start_mail AS ssm ON s.id = ssm.solicitation_id "
      "     JOIN dynamic_mail AS dm ON ssm.dynamic_mail_id = dm.id "
      "     WHERE s.id = %s; ",
    [(solicitationId)])
  except Exception as e:
    print("# Database reading error:")
    print(str(e))
    traceback.print_exc()
    return False
  
  return sendMails(solicitationMails, studentData)

def sendTransitionMails(transitionId, studentData=None, advisorData=None):
  try:
    transitionMails = dbGetAll(
      " SELECT dm.mail_subject, dm.mail_body_html, dm.is_sent_to_student, dm.is_sent_to_advisor, dm.is_sent_to_coordinator "
      "   FROM solicitation_state_transition AS sst "
      "     JOIN solicitation_state_transition_mail AS sstm ON sst.id = sstm.solicitation_state_transition_id "
      "     JOIN dynamic_mail AS dm ON sstm.dynamic_mail_id = dm.id "
      "     WHERE sst.id = %s; ",
      [(transitionId)])
  except Exception as e:
    print("# Database reading error:")
    print(str(e))
    traceback.print_exc()
    return False
  
  return sendMails(transitionMails, studentData, advisorData)

def sendMails(mailList, studentData=None, advisorData=None):
  
  try:
    for mail in mailList:
      
      # treat mail subject and body
      parsedSubject = sistemStrParser(mail["mail_subject"], studentData, advisorData)
      parsedBody = sistemStrParser(mail["mail_body_html"], studentData, advisorData)

      if mail["is_sent_to_student"]:
        addToSmtpMailServer(studentData['institutional_email'], parsedSubject, parsedBody)

      if mail["is_sent_to_advisor"]:
        addToSmtpMailServer(advisorData['institutional_email'], parsedSubject, parsedBody)

      if mail["is_sent_to_coordinator"]:
        addToSmtpMailServer(getCoordinatorEmail(), parsedSubject, parsedBody)

  except Exception as e:
    print("# Smtp sending error:")
    print(str(e))
    traceback.print_exc()
    return False

  return True
  
def resolveSolicitation(userHasStateId, userData, transitionId, solicitationUserData, scheduled):

  queryRes = None
  try:
    queryRes = dbGetSingle(
      " SELECT uc_stu.id AS student_id, uc_stu.user_name AS student_name, uc_stu.institutional_email AS student_institutional_email, "
      " uc_stu.secondary_email AS student_secondary_email, uc_stu.gender AS student_gender, "
      " uc_stu.phone AS student_phone, uc_stu.creation_datetime AS student_creation_datetime, "
      " uhpsd.matricula AS student_matricula, uhpsd.course AS student_course, "

      " uc_adv.id AS advisor_id, uc_adv.user_name AS advisor_name, uc_adv.institutional_email AS advisor_institutional_email, "
      " uc_adv.secondary_email AS advisor_secondary_email, uc_adv.gender AS advisor_gender, uc_adv.phone AS advisor_phone, "
      " uc_adv.creation_datetime AS advisor_creation_datetime, uhpad.siape AS advisor_siape, 3 AS advisor_students, "

      " uhs.id AS user_has_solicitation_id, uhs.solicitation_id, uhs.actual_solicitation_state_id, uhs.solicitation_user_data, "
      " uhss.solicitation_state_id, uhss.decision, uhss.start_datetime, uhss.end_datetime, "
      " sspe.profile_acronyms, "
      " dp.id AS page_id "
      "   FROM user_account AS uc_stu "
      "     JOIN user_has_profile AS uhp_stu ON uc_stu.id = uhp_stu.user_id "
      "     JOIN user_has_profile_student_data AS uhpsd ON uhp_stu.id = uhpsd.user_has_profile_id "
      "     JOIN user_has_solicitation AS uhs ON uc_stu.id = uhs.user_id "
      "     JOIN user_has_solicitation_state AS uhss ON uhs.id = uhss.user_has_solicitation_id "
      "     JOIN solicitation_state AS ss ON uhss.solicitation_state_id = ss.id "
      "     LEFT JOIN dynamic_page AS dp ON ss.state_dynamic_page_id = dp.id "
      "     LEFT JOIN user_has_profile_advisor_data AS uhpad ON uhs.advisor_siape = uhpad.siape "
      "     LEFT JOIN user_has_profile AS uhp_adv ON uhpad.user_has_profile_id = uhp_adv.id "
      "     LEFT JOIN user_account AS uc_adv ON uhp_adv.user_id = uc_adv.id "
      "     LEFT JOIN ( "
      "       SELECT sspe.solicitation_state_id, "
      "         GROUP_CONCAT(sspe.state_profile_editor) AS state_profile_editors, "
      "         GROUP_CONCAT(p.profile_acronym) AS profile_acronyms "
      "           FROM solicitation_state_profile_editors sspe "
      "           JOIN profile p ON sspe.state_profile_editor = p.id "
      "           GROUP BY sspe.solicitation_state_id) sspe ON ss.id = sspe.solicitation_state_id "
      "   WHERE uhss.id = %s; ",
      [(userHasStateId)])
    
  except Exception as e:
    print("# Database reading error:")
    print(str(e))
    traceback.print_exc()
    return "Erro na base de dados", 409

  if not queryRes:
    return "Usuario não possui o estado da solicitação!", 401

  # Data used by parser
  studentData={
    "user_id": queryRes["student_id"],
    "institutional_email": queryRes["student_institutional_email"],
    "user_name": queryRes["student_name"],
    "gender": queryRes["student_gender"],
    "profiles": [{
      "profile_acronym":"STU",
      "matricula": queryRes["student_matricula"],
      "course": queryRes["student_course"]
    }]
  }
  advisorData={
    "user_id": queryRes["advisor_id"],
    "institutional_email": queryRes["advisor_institutional_email"],
    "user_name": queryRes["advisor_name"],
    "gender": queryRes["advisor_gender"],
    "profiles": [{
      "profile_acronym":"ADV",
      "siape": queryRes["advisor_siape"]
    }]
  }

  userHasSolId = queryRes["user_has_solicitation_id"]
  solicitationId = queryRes["solicitation_id"]
  actualSolStateId = queryRes["actual_solicitation_state_id"]
  oldSolicitationUserData = getFormatedMySQLJSON(queryRes["solicitation_user_data"])
  stateId = queryRes["solicitation_state_id"]
  stateDecision = queryRes["decision"]
  stateStartDatetime = queryRes["start_datetime"]
  stateEndDatetime = queryRes["end_datetime"]
  stateProfileAcronymEditors = queryRes["profile_acronyms"]
  pageId = queryRes["page_id"]

  # Verify solicitation args correcteness
  print("# Validating data")

  # if not adm check if is student or advisor
  if not "ADM" in userData["profile_acronyms"] and not "COO" in userData["profile_acronyms"]:
    if userData["user_id"] != studentData["user_id"] and userData["user_id"] != advisorData["user_id"]:
      return "Edição a solicitação não permitida!", 401

  # checks if profile is allowed to change solicitation
  profileCanEdit = False
  for profileEditor in stateProfileAcronymEditors.split(','):
    if profileEditor in userData["profile_acronyms"]:
      profileCanEdit = True
  
  # checks if if the solicitation is actual and editable
  if not scheduled and not profileCanEdit:
    return "Perfil editor a solicitação inválido!", 401
  if actualSolStateId!=stateId:
    return "Edição do estado da solicitação não permitido!", 401

  # data validation
  if stateStartDatetime and datetime.now() < stateStartDatetime:
    return "Esta etapa da solicitação não foi iniciada!", 401
  if stateEndDatetime and datetime.now() > stateEndDatetime:
    return "Esta etapa da solicitação foi expirada!", 401
  if stateDecision != "Em analise":
    return "Esta solicitação já foi realizada!", 401

  # verify transitions
  transitions = getTransitions(stateId)

  if not transitions or len(transitions) == 0:
    return "Solicitação inválida!", 401

  transition = None
  for ts in transitions:
    if ts["id"] == transitionId:
      transition = ts
      break
  
  if transition == None:
    return "Transição não encontrada para este estado!", 404

  if transition["type"] == "from_dynamic_page":

    dynamicPage = None
    try:
      dynamicPage = getDynamicPage(pageId)
    except Exception as e:
      print("# Database reading error:")
      print(str(e))
      traceback.print_exc()
      return "Erro na base de dados", 409

    for component in dynamicPage["components"]:

      # Checks if all required inputs are valid
      if component["component_type"] == "input" and component["input_required"]:
        found = False
        
        for userInput in solicitationUserData['inputs']:
          if userInput["input_name"] == component["input_name"]:
            found = True
          
        if not found:
          return "Input da solicitação está faltando!", 401

      # Checks if all required uploads are valid
      if component["component_type"] == "upload" and component["upload_required"]:
        found = False

        for userUpload in solicitationUserData["uploads"]:

          if userUpload["upload_name"] == component["upload_name"]:
            try:
              if dbGetSingle(
                  " SELECT att.hash_name "
                  "   FROM attachment AS att JOIN user_has_attachment AS uhatt ON att.id = uhatt.attachment_id "
                  "   WHERE uhatt.user_id = %s AND att.hash_name = %s; ",
                  [userData["user_id"], userUpload["upload_hash_name"]]):
                found = True
                break
            except Exception as e:
              print("# Database reading error:")
              print(str(e))
              traceback.print_exc()
              return "Erro na base de dados", 409
                
        if not found:
          return "Anexo da solicitação está faltando!", 401
              
      # Checks if all required select uploads are valid - incomplete
      if component["component_type"] == "select_upload" and component["select_upload_required"]:
        pass
  
  # get next state data
  try:
    queryRes = dbGetSingle(
      " SELECT ss.id AS state_id, ss.state_max_duration_days, sspe.profile_acronyms "
      "   FROM solicitation_state_transition AS sst "
      "     LEFT JOIN solicitation_state AS ss ON sst.solicitation_state_id_to = ss.id "
      "     LEFT JOIN ( "
      "       SELECT sspe.solicitation_state_id, "
      "         GROUP_CONCAT(sspe.state_profile_editor) AS state_profile_editors, "
      "         GROUP_CONCAT(p.profile_acronym) AS profile_acronyms "
      "           FROM solicitation_state_profile_editors sspe "
      "           JOIN profile p ON sspe.state_profile_editor = p.id "
      "           GROUP BY sspe.solicitation_state_id) sspe ON ss.id = sspe.solicitation_state_id "
      "     WHERE sst.id = %s; ",
      (transitionId,))
    
    if not queryRes:
      raise Exception("No return for next state data")

  except Exception as e:
    print("# Database reading error:")
    print(str(e))
    traceback.print_exc()
    return "Erro na base de dados", 409
  
  transitionDecision = transition["transition_decision"]
  transitionReason = transition["transition_reason"]
  nextStateId = transition["solicitation_state_id_to"]
  nextStateMaxDays = queryRes["state_max_duration_days"]
  nextStateProfileEditorAcronyms = queryRes["profile_acronyms"]

  # parse solicitation data
  newSolicitationUserData = None
  if oldSolicitationUserData:
    newSolicitationUserData = oldSolicitationUserData
  else:
    newSolicitationUserData = {
      "inputs": {},
      "uploads": {},
      "select_uploads": {}
    }

  if solicitationUserData:
    for input in solicitationUserData["inputs"]:
      newSolicitationUserData["inputs"][input["input_name"]] = input
    for upload in solicitationUserData["uploads"]:
      newSolicitationUserData["uploads"][upload["upload_name"]] = upload
    for selectUpload in solicitationUserData["select_uploads"]:
      newSolicitationUserData["select_uploads"][selectUpload["select_upload_name"]] = selectUpload
  
  newSolicitationUserData = json.dumps(newSolicitationUserData)
  
  # start transaction
  dbObjectIns = dbStartTransactionObj()
  print("# Updating and Inserting data in db")
  try:
    # updates actual user state
    dbExecute(
      " UPDATE user_has_solicitation_state "
      "   SET decision = %s, reason = %s "
      "   WHERE id = %s; ",
      [transitionDecision, transitionReason, userHasStateId], True, dbObjectIns)
    
    # remove old events from scheduler
    removeScheduledSolicitation(userHasStateId, True, dbObjectIns)

    # if next state exists
    if nextStateId:
      nextStateCreatedDate = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
      nextStateFinishDate = None if not nextStateMaxDays else (datetime.now() + timedelta(days=nextStateMaxDays)).strftime("%Y-%m-%d %H:%M:%S")

      nextStateReason = ''
      sendProfileNames = None
      if nextStateProfileEditorAcronyms:
        if "STU" in nextStateProfileEditorAcronyms:
          sendProfileNames = "aluno"
        if "ADV" in nextStateProfileEditorAcronyms:
          sendProfileNames = "orientador" if not sendProfileNames else sendProfileNames + ", orientador"
        if "COO" in nextStateProfileEditorAcronyms:
          sendProfileNames = "coordenação de estágios" if not sendProfileNames else sendProfileNames + ", coordenação de estágios"
        if "," in sendProfileNames:
          lastIndex = sendProfileNames.rfind(",")
          sendProfileNames = sendProfileNames[:lastIndex] + " e" + sendProfileNames[lastIndex+1:]

        if sendProfileNames == "coordenação de estágios":
          nextStateReason = "Aguardando a coordenação de estágios"
        else:
          nextStateReason = ("Aguardando o " + sendProfileNames) if sendProfileNames else None
      else:
        nextStateReason = "Finalizado"
        
      # inserts new user state
      dbExecute(
        " INSERT INTO user_has_solicitation_state "
        " (user_has_solicitation_id, solicitation_state_id, decision, reason, start_datetime, end_datetime) VALUES "
        "   (%s, %s, DEFAULT, %s, %s, %s); ",
        [
          userHasSolId,
          nextStateId,
          nextStateReason,
          nextStateCreatedDate,
          nextStateFinishDate],
        True, dbObjectIns)

      userHasNextStateId = dbGetSingle("SELECT LAST_INSERT_ID() AS id;", (), True, dbObjectIns)['id']
      nextStateTransitions = getTransitions(nextStateId)

      # updates user solicitation data and changes its actual state
      dbExecute(
        " UPDATE user_has_solicitation "
        "   SET actual_solicitation_state_id = %s, solicitation_user_data = %s "
        "   WHERE id = %s; ",
        [nextStateId, newSolicitationUserData, userHasSolId], True, dbObjectIns)

      # sets schedule
      scheduleTransitions(userHasNextStateId, userData, nextStateTransitions, True, dbObjectIns)

    # if next state not exists
    else:
      # updates only user solicitation data
      dbExecute(
        " UPDATE user_has_solicitation "
        "   SET solicitation_user_data = %s "
        "   WHERE id = %s; ",
        [newSolicitationUserData, userHasSolId], True, dbObjectIns)
      
  except Exception as e:
    dbRollback(dbObjectIns)
    print("# Database reading error:")
    print(str(e))
    traceback.print_exc()
    return "Erro na base de dados", 409

  dbCommit(dbObjectIns)
  print("# Solicitation done!\n# Sending mails")

  sendTransitionMails(transitionId, studentData, advisorData)
  print("# Operation done!")

  return {}, 200

def scheduleTransitions(userHasStateId, userData, stateTransitions,  transactionMode, dbObjectIns):

  for transition in stateTransitions:
    if transition["type"] == "scheduled":

      sendDatetime = (datetime.now() + timedelta(seconds=transition["transition_delay_seconds"]))
      sendDatetimeFormated = sendDatetime.strftime("%Y-%m-%d %H:%M:%S")

      # insert scheduling
      dbExecute(
        " INSERT INTO scheduling "
        " (scheduled_action, scheduled_datetime) VALUES "
        "   (%s, %s); ",
        ["Solicitation State Transition", sendDatetimeFormated], transactionMode, dbObjectIns)

      # select added scheduling id
      scheduledId = dbGetSingle("SELECT LAST_INSERT_ID() AS id;", (), transactionMode, dbObjectIns)['id']
      
      # insert transition to schedule table
      dbExecute(
        " INSERT INTO scheduling_state_transition "
        " (scheduling_id, state_transition_scheduled_id, user_has_solicitation_state_id) VALUES "
        "   (%s, %s, %s); ",
        [scheduledId, transition["id"], userHasStateId], transactionMode, dbObjectIns)

      # insert to system schedule
      addTransitionToEventScheduler(scheduledId, sendDatetime, userHasStateId, userData, transition["id"], resolveScheduledSolicitation)

def resolveScheduledSolicitation(eventId, userHasStateId, userData, transitionId):

  print("\n# Starting scheduled solicitation for " + userData["institutional_email"] + "\n# Reading data from DB")

  dbExecute(
    " UPDATE scheduling SET "
    "   scheduled_status = %s "
    "   WHERE id = %s ",
    ["Sended", eventId])
  
  response, status = resolveSolicitation(userHasStateId, userData, transitionId, None, True)

  if status != 200:
    print(f"# EventScheduler thread {threading.get_ident()}: Error: {response}, {status}")
  else:
    print(f'# EventScheduler thread {threading.get_ident()}: Done without errors')

def removeScheduledSolicitation(userHasStateId, transactionMode, dbObjectIns):

  schQuery = """
    SELECT sch.id AS id, sch.scheduled_action, sch.scheduled_datetime, sch.scheduled_status, 
    scht.state_transition_scheduled_id, scht.user_has_solicitation_state_id  
      FROM sisgesteste.scheduling sch 
      JOIN scheduling_state_transition scht ON sch.id = scht.scheduling_id
      WHERE user_has_solicitation_state_id = %s;
    """
  schs = dbGetAll(schQuery,(userHasStateId,), transactionMode, dbObjectIns)

  for sch in schs:
    removeEventFromScheduler(sch['id'])
    dbExecute(
      " UPDATE scheduling SET "
      "   scheduled_status = %s "
      "   WHERE id = %s; ",
      ["Canceled", sch['id']],  transactionMode, dbObjectIns)

# Data from single solicitation
class Solicitation(Resource):

  # get single solicitation and associated dynamic page data
  def get(self):

    args = reqparse.RequestParser()
    args.add_argument("Authorization", location="headers", type=str, help="Bearer with jwt given by server in user autentication, required", required=True)
    args.add_argument("user_has_state_id", location="args", type=int, required=True)
    args = args.parse_args()

    # verify jwt and its signature correctness
    isTokenValid, errorMsg, tokenData = isAuthTokenValid(args)
    if not isTokenValid:
      abort(401, errorMsg)

    userHasStateId = args["user_has_state_id"]

    print("\n# Starting get single solicitation for " + tokenData["institutional_email"] + "\n# Reading data from DB")

    queryRes = None
    try:
      queryRes = dbGetSingle(
        " SELECT uhs.user_id, uc_adv.id AS advisor_id "
        "   FROM user_has_solicitation_state AS uhss "
        "     JOIN user_has_solicitation AS uhs ON uhss.user_has_solicitation_id = uhs.id "
        "     LEFT JOIN user_has_profile_advisor_data AS uhpad ON uhs.advisor_siape = uhpad.siape "
        "     LEFT JOIN user_has_profile AS uhp_adv ON uhpad.user_has_profile_id = uhp_adv.id "
        "     LEFT JOIN user_account AS uc_adv ON uhp_adv.user_id = uc_adv.id "
        "   WHERE uhss.id = %s; ",
        [(userHasStateId)])
    except Exception as e:
      print("# Database reading error:")
      print(str(e))
      traceback.print_exc()
      return "Erro na base de dados", 409

    if not queryRes:
      abort(401, "Usuario não possui o estado da solicitação!")

    studentId = queryRes["user_id"]
    advisorId = queryRes["advisor_id"]

    if not "ADM" in tokenData["profile_acronyms"] and not "COO" in tokenData["profile_acronyms"]:
      if tokenData["user_id"] != studentId and tokenData["user_id"] != advisorId:
        abort(401, "Acesso a solicitação não permitido!")

    solicitationQuery = None
    try:
      solicitationQuery = dbGetSingle(
        " SELECT uc_stu.user_name AS student_name, uc_stu.institutional_email AS student_institutional_email, "
        " uc_stu.secondary_email AS student_secondary_email, uc_stu.gender AS student_gender, "
        " uc_stu.phone AS student_phone, uc_stu.creation_datetime AS student_creation_datetime, "
        " uhpsd.matricula AS student_matricula, uhpsd.course AS student_course, "

        " uc_adv.user_name AS advisor_name, uc_adv.institutional_email AS advisor_institutional_email, "
        " uc_adv.secondary_email AS advisor_secondary_email, uc_adv.gender AS advisor_gender, uc_adv.phone AS advisor_phone, "
        " uc_adv.creation_datetime AS advisor_creation_datetime, uhpad.siape AS advisor_siape, 3 AS advisor_students, "

        " s.solicitation_name, "
        " ss.id AS state_id, ss.state_description, ss.state_max_duration_days, "
        " uhs.id AS user_has_solicitation_id, uhs.is_accepted_by_advisor, uhs.actual_solicitation_state_id, uhs.solicitation_user_data, "
        " uhss.id AS user_has_state_id, uhss.decision, uhss.reason, uhss.start_datetime, uhss.end_datetime, "
        " ss.state_dynamic_page_id AS page_id, "
        " sspe.profile_acronyms "
        
        "   FROM user_account AS uc_stu "
        "     JOIN user_has_profile AS uhp_stu ON uc_stu.id = uhp_stu.user_id "
        "     JOIN user_has_profile_student_data AS uhpsd ON uhp_stu.id = uhpsd.user_has_profile_id "

        "     JOIN user_has_solicitation AS uhs ON uc_stu.id = uhs.user_id "
        "     JOIN user_has_solicitation_state AS uhss ON uhs.id = uhss.user_has_solicitation_id "
        "     JOIN solicitation AS s ON uhs.solicitation_id = s.id "
        "     JOIN solicitation_state AS ss ON uhss.solicitation_state_id = ss.id "

        "     LEFT JOIN user_has_profile_advisor_data AS uhpad ON uhs.advisor_siape = uhpad.siape "
        "     LEFT JOIN user_has_profile AS uhp_adv ON uhpad.user_has_profile_id = uhp_adv.id "
        "     LEFT JOIN user_account AS uc_adv ON uhp_adv.user_id = uc_adv.id "

        "     LEFT JOIN ( "
        "       SELECT sspe.solicitation_state_id, "
        "         GROUP_CONCAT(sspe.state_profile_editor) AS state_profile_editors, "
        "         GROUP_CONCAT(p.profile_acronym) AS profile_acronyms "
        "           FROM solicitation_state_profile_editors sspe "
        "           JOIN profile p ON sspe.state_profile_editor = p.id "
        "           GROUP BY sspe.solicitation_state_id) sspe ON ss.id = sspe.solicitation_state_id "
        
        "   WHERE uc_stu.id = %s AND uhss.id = %s; ",
        [studentId, userHasStateId])
      
    except Exception as e:
      print("# Database reading error:")
      print(str(e))
      traceback.print_exc()
      return "Erro na base de dados", 409

    if not solicitationQuery:
      abort(401, "Usuario não possui o estado da solicitação!")

    # Tokens for parsing string
    studentParserToken={
      "user_name": solicitationQuery["student_name"],
      "gender": solicitationQuery["student_gender"],
      "profiles": [{
        "profile_acronym":"STU",
        "matricula": solicitationQuery["student_matricula"],
        "course": solicitationQuery["student_course"]
      }]
    }
    professorParserToken={
      "user_name": solicitationQuery["advisor_name"],
      "gender": solicitationQuery["advisor_gender"],
      "profiles": [{
        "profile_acronym":"ADV",
        "siape": solicitationQuery["advisor_siape"]
      }]
    }
    
    dynamicPage = None
    if solicitationQuery["page_id"]:
      dynamicPage = getDynamicPage(solicitationQuery["page_id"], studentParserToken, professorParserToken)
    
    transitions = getTransitions(solicitationQuery["state_id"])

    print("# Operation Done!")
    
    return {
      "student": {
        "user_name": solicitationQuery["student_name"],
        "institutional_email": solicitationQuery["student_institutional_email"],
        "secondary_email": solicitationQuery["student_secondary_email"],
        "gender": solicitationQuery["student_gender"],
        "phone": solicitationQuery["student_phone"],
        "creation_datetime": str(solicitationQuery["student_creation_datetime"]),
        "matricula": solicitationQuery["student_matricula"],
        "course": solicitationQuery["student_course"]
      },
      "advisor": {
        "user_name": solicitationQuery["advisor_name"],
        "institutional_email": solicitationQuery["advisor_institutional_email"],
        "secondary_email": solicitationQuery["advisor_secondary_email"],
        "gender": solicitationQuery["advisor_gender"],
        "phone": solicitationQuery["advisor_phone"],
        "creation_datetime": str(solicitationQuery["advisor_creation_datetime"]),
        "siape": solicitationQuery["advisor_siape"],
        "advisor_students": solicitationQuery["advisor_students"]
      },
      "solicitation":{
        "solicitation_name": solicitationQuery["solicitation_name"],
        "state_profile_editor_acronyms": solicitationQuery["profile_acronyms"],
        "state_description": solicitationQuery["state_description"],
        "state_max_duration_days": solicitationQuery["state_max_duration_days"],
        "actual_solicitation_state_id": solicitationQuery["actual_solicitation_state_id"],
        "solicitation_user_data": getFormatedMySQLJSON(solicitationQuery["solicitation_user_data"]),
        "user_has_solicitation_id": solicitationQuery["user_has_solicitation_id"],
        "user_has_state_id": solicitationQuery["user_has_state_id"],
        "is_accepted_by_advisor": solicitationQuery["is_accepted_by_advisor"],
        "decision": solicitationQuery["decision"],
        "reason": solicitationQuery["reason"],
        "start_datetime": str(solicitationQuery["start_datetime"]),
        "end_datetime": str(solicitationQuery["end_datetime"]),
        "transitions": transitions,
        "page": dynamicPage
      },
    }, 200
  
  # put to create solicitations - only for students
  def put(self):

    args = reqparse.RequestParser()
    args.add_argument("Authorization", location="headers", type=str, help="Bearer with jwt given by server in user autentication, required", required=True)
    args.add_argument("solicitation_id", location="json", type=int, required=True)
    args = args.parse_args()

    # verify jwt and its signature correctness
    isTokenValid, errorMsg, studentData = isAuthTokenValid(args, ["STU"])
    if not isTokenValid:
      abort(401, errorMsg)

    print("\n# Starting put Single Solicitation for " + studentData["institutional_email"] + "\n# Reading data from DB")
    
    stateId = None
    stateTransitions = None
    stateMaxDurationDays = None
    queryRes = None
    try:
      queryRes = dbGetSingle(
        " SELECT ss.id AS state_id, ss.state_max_duration_days "
        "   FROM solicitation AS s JOIN solicitation_state AS ss ON s.id = ss.solicitation_id "
        "   WHERE s.id = %s AND ss.is_initial_state = TRUE; ",
        [(args["solicitation_id"])])

      if not queryRes:
        raise Exception("No initial state return for solicitation with id " + str(args["solicitation_id"]))
      
      stateId = queryRes["state_id"]
      stateMaxDurationDays = queryRes["state_max_duration_days"]
      stateTransitions = getTransitions(stateId)

      queryRes = dbGetSingle(
        " SELECT s.id	FROM user_account AS us "
	      "   JOIN user_has_solicitation AS uhs ON us.id = uhs.user_id "
	      "   JOIN solicitation AS s ON uhs.solicitation_id = s.id "
	      "   WHERE s.id = %s AND us.id = %s; ",
        [args["solicitation_id"], studentData["user_id"]])

    except Exception as e:
      print("# Database reading error:")
      print(str(e))
      traceback.print_exc()
      return "Erro na base de dados", 409

    if queryRes:
      abort(401, "Você já possui essa solicitação!")
    
    # set created date and finish date based on max day interval from solicitation state
    createdDate = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    finishDate = None if not stateMaxDurationDays else (datetime.now() + timedelta(days=stateMaxDurationDays)).strftime("%Y-%m-%d %H:%M:%S")
    
    userHasSolId = None
    userHasStateId = None

    print("# Sending mails")
    mailsSended = sendSolicitationMails(args["solicitation_id"], studentData)
    if not mailsSended:
      raise Exception("Error while sending start solicitation mails")

    # start transaction
    dbObjectIns = dbStartTransactionObj()
    try:
      # insert user solicitation
      dbExecute(
        " INSERT INTO user_has_solicitation "
        " (user_id, advisor_siape, solicitation_id, actual_solicitation_state_id, solicitation_user_data) VALUES "
        "   (%s, NULL, %s, %s, NULL); ",
        [studentData["user_id"], args["solicitation_id"], stateId], True, dbObjectIns)

      # select added user solicitation id
      queryRes = dbGetSingle(
        " SELECT uhs.id "
        "   FROM user_has_solicitation AS uhs "
        "   WHERE uhs.user_id = %s AND solicitation_id = %s; ",
        [studentData["user_id"], args["solicitation_id"]], True, dbObjectIns)
      
      if not queryRes:
        raise Exception("No return for user_has_solicitation insertion ")

      userHasSolId = queryRes["id"]

      # insert user solicitation state
      dbExecute(
        " INSERT INTO user_has_solicitation_state "
        " (user_has_solicitation_id, solicitation_state_id, decision, reason, start_datetime, end_datetime) VALUES "
        "   (%s, %s, \"Em analise\", \"Aguardando o aluno\", %s, %s); ",
        [userHasSolId, stateId, createdDate, finishDate], True, dbObjectIns)

      # select added user solicitation state id
      queryRes = dbGetSingle(
        " SELECT uhss.id "
        "   FROM user_has_solicitation_state AS uhss "
        "   WHERE uhss.user_has_solicitation_id = %s AND uhss.solicitation_state_id = %s; ",
        [userHasSolId, stateId], True, dbObjectIns)

      if not queryRes:
        raise Exception("No return for user_has_solicitation_state insertion ")
      
      userHasStateId = queryRes["id"]

      # schedule transitions for initial state if any
      scheduleTransitions(userHasStateId, studentData, stateTransitions, True, dbObjectIns)

    except Exception as e:
      dbRollback(dbObjectIns)
      print("# Database reading error:")
      print(str(e))
      traceback.print_exc()
      return "Erro na base de dados", 409

    # ends transaction
    dbCommit(dbObjectIns)
    print("# Operation done!")
    return { "user_has_solicitation_id": userHasSolId, "user_has_state_id": userHasStateId }, 200
      
  # post to resolve solicitations
  def post(self):

    args = reqparse.RequestParser()
    args.add_argument("Authorization", location="headers", type=str, help="Bearer with jwt given by server in user autentication, required", required=True)
    args.add_argument("user_has_state_id", location="json", type=int, required=True)
    args.add_argument("solicitation_user_data", location="json", required=True)
    args.add_argument("transition_id", location="json", type=int, required=True)
    args = args.parse_args()

    # verify jwt and its signature correctness
    isTokenValid, errorMsg, tokenUserData = isAuthTokenValid(args)
    if not isTokenValid:
      abort(401, errorMsg)

    # parsing args data
    userHasStateId = args["user_has_state_id"]
    solicitationUserData = args["solicitation_user_data"]
    transitionId = args["transition_id"]

    if solicitationUserData:
      solicitationUserData = json.loads(
        solicitationUserData.replace("\'", "\"") if isinstance(solicitationUserData, str) else solicitationUserData.decode("utf-8"))
    
    print("\n# Starting post to resolve solicitation for " + tokenUserData["institutional_email"] + "\n# Reading data from DB")
    response, status = resolveSolicitation(userHasStateId, tokenUserData, transitionId, solicitationUserData, False)
    return response, status