#!/usr/bin/env python3
from cProfile import label
import os,sys,glob,time,shutil,argparse,json,traceback,re
import numpy as np

from dflow import (
    Workflow,
    download_artifact,
)

import  os, shutil, glob
from . import globV,dflowOP,comm

def ParamParser(param):
    """
    {
        "bohrium_goup_name": ,
        "ABBREVIATION":{},
        "save_path" : PATH_THE_FINAL_RESULT_WILL_BE_DOWNLOADED_TO,
        "pre_dft":{},
        "run_dft" : {},
        "post_dft": {},
        "report":{}
    }
    """
    
    alljobs = {}

    alljobs["save_path"] = param.get("save_path",None)
    alljobs["prepare"] = param.get("prepare",{"ifrun":False})
    alljobs["pre_dft"] = param.get("pre_dft",{"ifrun":False})
    alljobs["run_dft"] = param.get("run_dft",{"ifrun":False})
    alljobs["post_dft"] = param.get("post_dft",{"ifrun":False})
#    alljobs["upload_datahub"] = param.get("upload_datahub",None)  #used to upload local files to datahub
#    alljobs["upload_tracking"] = param.get("upload_tracking",None)  #used to upload tracking
    alljobs["report"] = param.get("report",None)
    alljobs["bohrium_group_name"] = "abacustesting"
    if param.get("bohrium_group_name","") != "":
        alljobs["bohrium_group_name"] = param.get("bohrium_group_name")
    elif param.get("config",{}).get("dflow_labels",{}).get("launching-job"):
        bohriu_name = param.get("config",{}).get("dflow_labels",{}).get("launching-job")
        if bohriu_name.startswith("sched-abacustest-"):
            alljobs["bohrium_group_name"] = "s-" + bohriu_name[17:]
        elif bohriu_name.startswith("job-abacustest-"):
            alljobs["bohrium_group_name"] = "j-" + bohriu_name[15:]
        else:
            alljobs["bohrium_group_name"] = bohriu_name
        
    alljobs["ABBREVIATION"] = param.get("ABBREVIATION",{})

    #print(alljobs)
    #sys.exit(1)
    globV.set_value("ABBREVIATION",alljobs.get('ABBREVIATION',{}))
    return alljobs

def SetSaveFolder(storefolder=None):
    if storefolder == None:
        #import datetime
        #from time import strftime
        #today = datetime.datetime.now()
        #today = today.strftime("%Y%m%d")
        #storefolder = os.path.join("result",today)
        storefolder = "result"
    globV.set_value("RESULT",storefolder)
    comm.printinfo("set save floder: %s" % storefolder)

def MakeSaveFolder(storefolder=None):
    storefolder = globV.get_value("RESULT") if storefolder == None else storefolder
    storefolder = storefolder.strip().strip("/")
    if not os.path.isdir(storefolder):
        os.makedirs(storefolder)
    elif not globV.get_value("OVERRIDE"):
        n = 1
        bk = storefolder + ".bk%d" % n
        while os.path.isdir(bk):
            n += 1
            bk = storefolder + ".bk%d" % n
        os.rename(storefolder,bk)
        comm.printinfo("Folder %s is exist, rename to %s" % (storefolder,bk))
        os.makedirs(storefolder)
    
def WriteParamUserFile(storefolder=None,override=False):
    storefolder = globV.get_value("RESULT") if storefolder == None else storefolder
    paraf = os.path.join(storefolder,globV.get_value("PARAM_FNAME")) 
    
    if not override:
        def getfname(paraf):
            paraf_tmp = paraf
            n = 1
            while os.path.isfile(paraf_tmp):
                paraf_tmp = paraf + "%d" % n
                n += 1
            return paraf_tmp
            
        paraf = getfname(paraf)

    save_cotext = {}
    for k,v in globV.get_value("PARAM_CONTEXT").items():
        if k in ["config"]:
            continue
        
        # hide the config information in dispatcher
        if isinstance(v,dict):
            if "dispatcher" in v:
                comm.hide_config_in_dispatcher(v["dispatcher"])
        elif isinstance(v,list):
            for i in range(len(v)):
                if isinstance(v[i],dict):
                    if "dispatcher" in v[i]:
                        comm.hide_config_in_dispatcher(v[i]["dispatcher"])
        save_cotext[k] = v
    json.dump(save_cotext,open(paraf,'w'),indent=4)
    #with open(paraf,'w') as f1: f1.write(globV.get_value("PARAM_CONTEXT")) 

def set_config(param_context,debug):
    # read config from param.json and os.environ
    # key in param.json should be lower case, and in os.environ should be upper case
    # support older key name, such as "bohrium_username" and "lbg_username"
    '''
    old keys:   "lbg_username","lbg_password","bohrium_ticket","project_id",
                 "config_host","s3_config_endpoint","config_k8s_api_server","config_token",
                 "datahub_project","datahub_gms_token","datahub_gms_url","AIM_ACCESS_TOKEN",
                 "dflow_labels"
    datahub is not used anymore.
    '''
    
    if "config" in param_context:
        user_context = param_context.get("config")
    else:
        comm.printinfo(f"WARNING: \"config\" is not detected in parameter file, try to read config information from os.environ.")
        user_context = {}
    
    configs = {} 
    for new_key,old_key in [["bohrium_username","lbg_username"],
                            ["bohrium_password","lbg_password"],
                            ["bohrium_ticket","bohrium_ticket"],
                            ["bohrium_project_id","project_id"],
                            ["dflow_host","config_host"],
                            ["dflow_s3_config_endpoint","s3_config_endpoint"],
                            ["dflow_k8s_api_server","config_k8s_api_server"],
                            ["dflow_token","config_token"],
                            ["dflow_labels","dflow_labels"],   # dflow_labels is a dict
                            ["aim_access_token","AIM_ACCESS_TOKEN"],
    ]:
        if new_key in user_context:
            configs[new_key] = user_context.pop(new_key)
        elif old_key in user_context:
            configs[new_key] = user_context.pop(old_key)
        elif new_key.upper() in os.environ:
            configs[new_key] = os.environ[new_key.upper()]
        elif old_key.upper() in os.environ:
            configs[new_key] = os.environ[old_key.upper()]
    
    if "dflow_labels" in configs and isinstance(configs["dflow_labels"],str):
        if configs["dflow_labels"].strip() != "":
            import ast
            configs["dflow_labels"] = ast.literal_eval(configs["dflow_labels"].strip())
        else:
            del configs["dflow_labels"]
    
    for ik,iv in user_context.items():
        configs[ik] = iv    
            
    globV.set_value("PRIVATE_SET", configs)
    
    if configs.get("dflow_labels",None) != None:
        job_address = "https://labs.dp.tech/projects/abacustest/?request=GET%3A%2Fapplications%2Fabacustest%2Fjobs%2F" + configs["dflow_labels"]["launching-job"]
        globV.set_value("JOB_ADDRESS",job_address)
    
    dflowOP.SetConfig(configs,debug=debug)
    return 
    
def set_env(param):
    globV.set_value("OUTINFO", param.outinfo)
    globV.set_value("OVERRIDE", param.override)
    comm.printinfo("\nSet enviroment ...")
    comm.printinfo(param)

    #read job.json
    if not os.path.isfile(param.param):
        comm.printinfo("ERROR: Can not find the test setting file '%s' " % param.param)
        sys.exit(1)
    comm.printinfo("Read parameter setting from %s" % param.param)
    globV.set_value("PARAM_FNAME", os.path.split(param.param)[1]) 
    globV.set_value("PARAM_CONTEXT", json.load(open(param.param)))       
    param_context = json.load(open(param.param))
    globV.set_value("PARAM", param_context)
    
    #read user config information
    bohrium_executor = False
    if "bohrium_executor" in param_context:
        bohrium_executor = bool(param_context["bohrium_executor"])
    globV.set_value("BOHRIUM_EXECUTOR",bohrium_executor)
    
    set_config(param_context,param.debug)

    #set save folder  
    if param_context.get("save_path"):
        save_path = param_context.get("save_path")
    else:
        save_path = param.save
    SetSaveFolder(save_path)
    
    #report = param_context.get("report",{})
    #globV.set_value("REPORT", report)

    report = param_context.get("report",{})
    globV.set_value("REPORT", report)

def waitrun(wf,stepnames,allsave_path):
    '''
    stepnames = [[test1_stepname1,test1_stepname2,...],[test2_stepname1,test2_stepname2,...],...]
    allsave_path = [[[save_path,sub_save_path],[save_path,sub_save_path],...],[]...] similar to stepnames
    postdft_local_jobs = [[],[save_path,param["post_dft"]],[],..], null list means no postdft_local,
    '''
    finishtest = []
    makedfolder = []
    for i,istep in enumerate(stepnames):
        finishtest.append(len(istep)*[False])
    finishtest = np.array(finishtest)  
          
    wfid = wf.id

    while False in finishtest:
        for i,istep in enumerate(stepnames):
            for j,jfinish in enumerate(finishtest[i]):
                if jfinish:
                    continue
                steps = wf.query_step(name = istep[j])
                if len(steps) > 0: 
                    step = steps[0]
                    if step.phase in ["Pending","Running"]:
                        continue
                    finishtest[i][j] = True

                    save_path = allsave_path[i][j][0]
                    part_save_path = os.path.join(allsave_path[i][j][0],allsave_path[i][j][1])                      
                        
                    if part_save_path not in makedfolder:
                        MakeSaveFolder(part_save_path)
                        WriteParamUserFile(storefolder=part_save_path)
                        makedfolder.append(part_save_path)
                    comm.printinfo("%s is finished (remaining %d jobs for this test), download the results to %s!" % 
                                   (step.name,len(finishtest[i]) - np.sum(finishtest[i]),part_save_path))
                    if step.phase != 'Succeeded':
                        comm.printinfo("    This job is not Succeeded, please check on: %s, workflow ID is: %s" %
                              (globV.get_value("HOST"),wfid))  
                    try:
                        #print(step.outputs.artifacts["outputs"])
                        #print(step.outputs)
                        download_artifact(step.outputs.artifacts["outputs"],path=save_path)
                    except:
                        traceback.print_exc()
            if wf.query_status().strip() == "Failed":
                job_address = globV.get_value("HOST") + "/%s?tab=workflow" % wf.id
                comm.printinfo(f"The workflow is failed, please check on: {job_address}")  
                return
                    
                                
        time.sleep(4)

def ReportMetrics():
    report_setting = globV.get_value("report",{})
    if not report_setting or not report_setting.get("ifrun",True):
        return

    from abacustest import outresult
    allresults = outresult.GetAllResults(report_setting)
    if not allresults:
        return
    
    split_example=None if len(allresults["type_name"]) == 1 else "----"
    cc_outparam,allparam_value = outresult.OutParam(allresults,split_example=split_example)
    cc_outmetrics,allmetric_value = outresult.OutMetrics(allresults,allparam_value)
    
    #report
    from datetime import datetime
    param_context = globV.get_value("PARAM")
    report  = """\n\n\t\tABACUS TESTING REPORT\n"""
    report += "testing begin: %s\n" % globV.get_value("START_TIME").strftime("%d/%m/%Y %H:%M:%S")
    report += "testing   end: %s\n" % str(datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    report += "run_dft setting:\n"
    for irun in param_context.get("run_dft",[]):
        image = globV.get_value("ABBREVIATION").get(irun.get("image"),irun.get("image"))
        bohrium = irun.get("bohrium")
        report += "\timage: %s\n\tbohrium:%s\n\texample:%s\n" % (image,str(bohrium),str(irun.get("example")))
        
    if len(allresults["metrics"]) > 0:
        report += cc_outmetrics
    report += cc_outparam

    report_file = report_setting.get("save_file")
    if report_file != None:
        with open(report_file,'w') as f1:
            f1.write(report)
    comm.printinfo(report)

def RunJobs(param):
    set_env(param)
    alljobs = ParamParser(json.load(open(param.param)))
    allstep,stepname,allsave_path = dflowOP.ProduceAllStep(alljobs)

    if len(allstep) == 0:
        comm.printinfo("No step is produced, exit!!!")
    else:
        dflow_labels = globV.get_value("PRIVATE_SET",{}).get("dflow_labels",None)
        if globV.get_value("BOHRIUM_EXECUTOR"):
            wf = Workflow(name="abacustest",context=globV.get_value("BRM_CONTEXT"),labels=dflow_labels)
        else:
            wf = Workflow(name="abacustest",labels=dflow_labels)

        wf.add(allstep)
        wf.submit()
        if param.command == 'mlops-submit':
            return
        comm.printinfo("job ID: %s, UID: %s" % (wf.id,wf.uid))
        job_address = globV.get_value("HOST") + "/%s?tab=workflow" % wf.id
        comm.printinfo("You can track the flow by using your browser to access the URL:\n %s\n" % job_address)

        waitrun(wf,stepname,allsave_path)
    
    #if globV.get_value("REPORT"):
    #    ReportMetrics()
    
    if globV.get_value("REPORT"):
        comm.printinfo("\nGenerate html report ...")
        pwd = os.getcwd()
        if os.path.isdir(globV.get_value("RESULT")):
            os.chdir(globV.get_value("RESULT"))

        from abacustest import report
        filename = "abacustest.html"
        report.gen_html(globV.get_value("REPORT"),filename)
        
        os.chdir(pwd)
        
def CheckStatus(param):
    if os.path.isfile(param.param):
        private_set = json.load(open(param.param))
        if "config" in private_set:
            private_set = private_set["config"]
        elif "USER" in private_set:
            private_set = private_set["USER"]
    else:
        print("config file is not found!\nUse the default setting!")
        private_set = {}
        
    dflowOP.SetConfig(private_set,debug=False) 
    
    jobid = param.job_id
    
    wf = Workflow(id = jobid)
        
    try:
        return wf.query_status()
    except:
        comm.printinfo("Query status error")
        traceback.print_exc()
        return "not-running"
        
