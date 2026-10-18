/* Live UI QA: installed Chrome + maintained synthetic HTTP APIs; no model calls. */
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const {chromium} = require(process.env.FINAI_PLAYWRIGHT_MODULE || "playwright");
const evidence = path.join(__dirname,"../evidence");
const base = "http://127.0.0.1:8820";
const sleep = ms => new Promise(r=>setTimeout(r,ms));
(async()=>{
  const browser = await chromium.launch({headless:true, executablePath: process.env.FINAI_CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe"});
  const context = await browser.newContext({viewport:{width:1440,height:1080}});
  const page = await context.newPage();
  const errors=[]; const requests=[]; const report={fixture:"complete launcher-owned frozen v5 services", checks:[]};
  page.on("pageerror",e=>errors.push(e.message));
  page.on("request",r=>{if(r.url().startsWith(base+"/api/command")){const p=r.postDataJSON();requests.push({operation:p.operation, payload:p.payload});}});
  async function settled(){await page.locator("#busy").waitFor({state:"hidden",timeout:30000});}
  async function click(id){await page.locator(id).click();await settled();}
  async function snap(name,width){await page.setViewportSize({width,height:1080});await page.screenshot({path:path.join(evidence,name+".png"),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"page overflow at "+width);}
  try{
    await page.goto(base);await settled();
    assert.equal(await page.locator("#connection").innerText(),"Local services ready");
    assert(await page.locator("#execute").isDisabled());
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(()=>document.activeElement.textContent),"Skip to workspace");
    await page.keyboard.press("Tab");
    const focus=await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle);
    assert.notEqual(focus,"none");report.checks.push("keyboard navigation and visible focus");
    await click("#new-session");
    assert(await page.locator("#execute").isDisabled());report.checks.push("C: execution prevented before confirmation/admission");
    await page.locator("#message").fill("I want to reach SGD 200000 from SGD 50000 with SGD 1000 monthly in 10 years.");
    await click("#send");assert.equal(await page.locator("#readiness").innerText(),"READY");
    assert((await page.locator("#objective").innerText()).includes("120 months"));
    await click("#confirm");assert.equal(await page.locator("#readiness").innerText(),"CONFIRMED");
    // Preserve server outcome but deliberately lose the browser planning response.
    let lost=false;
    await page.route("**/api/command", async route=>{
      const payload=route.request().postDataJSON();
      if(payload.operation==="plan"&&!lost){lost=true;await route.fetch();await route.abort("failed");}
      else await route.continue();
    });
    await click("#plan");assert(lost);assert(await page.locator("#execute").isDisabled());
    await page.unroute("**/api/command");
    await click("#refresh");
    assert(!(await page.locator("#execute").isDisabled()),"lost planning response recovered");
    assert.equal(await page.locator(".task").count(),2);
    assert((await page.locator("#plan-graph").innerText()).includes("Depends on: goal"));
    report.checks.push("lost planning response recovered using backend attempt receipt without replanning");
    await snap("desktop-plan",1440);
    await click("#execute");
    await page.waitForFunction(()=>document.getElementById("run-status").textContent.includes("SUCCEEDED"),{timeout:30000});
    assert((await page.locator("#run-status").innerText()).includes("SUCCEEDED"));
    assert.equal(await page.locator(".result").count(),2);
    const result=JSON.parse(await page.locator("#raw").textContent());
    assert.equal(result.attempt.runtime.admission.source_tree,"1a196f3645d26cfaaeddf4952bf79a1a0175c7d398fb6a1277cfb856b4de8995");
    assert.equal(result.run.status,"SUCCEEDED");
    assert.deepEqual(Object.keys(result.run.results).sort(),["goal","risk"]);
    for(const item of Object.values(result.run.results)){
      assert.equal(item.label,"MOCK");assert.equal(item.run_id,result.run.run_id);
      assert.equal(item.objective_id,result.objective.objective_id);
      assert.equal(item.revision,result.objective.revision);
    }
    const dispatch=result.events.filter(e=>e.method==="POST"); assert.equal(dispatch.length,2);
    report.goal={session:result.objective.session_id, objective:result.objective.objective_id,
      plan:result.attempt.plan_id, request:result.attempt.request_id,trace:result.attempt.trace_id,
      run:result.run.run_id,status:result.run.status,results:Object.keys(result.run.results),events:result.events};
    fs.writeFileSync(path.join(evidence,"goal-http-evidence.json"),JSON.stringify(result,null,2));
    report.checks.push("A: READY, explicit CONFIRMED, POLICY_ONLY admitted Goal -> Risk, SUCCEEDED and exactly two bound MOCK results");
    const before=requests.filter(r=>r.operation==="execute").length;
    await page.reload();await settled();
    assert((await page.locator("#run-status").innerText()).includes("SUCCEEDED"));
    assert.equal(requests.filter(r=>r.operation==="execute").length,before);
    assert(await page.locator("#execute").isDisabled());report.checks.push("refresh recovers server run/events without resubmitting execution");
    await snap("desktop-results",1440);await snap("laptop-results",1024);await snap("mobile-results",390);
    await page.setViewportSize({width:1440,height:1080});
    await click("#new-session");
    await page.locator("#message").fill("I want to reach SGD 200000.");await click("#send");
    assert.equal(await page.locator("#readiness").innerText(),"NEEDS_INPUT");
    assert(await page.locator("#confirm").isDisabled());assert(await page.locator("#execute").isDisabled());
    await page.locator("#message").fill("from SGD 50000 with SGD 1000 monthly in 10 years");await click("#send");
    assert.equal(await page.locator("#readiness").innerText(),"READY");await click("#confirm");
    const revision=JSON.parse(await page.locator("#raw").textContent()).objective.revision;
    await page.locator(".edit-section").evaluate(node=>node.open=true);
    await page.locator("#edit-field").selectOption("target_amount");await page.locator("#edit-value").fill("250000");await click("#edit");
    const corrected=JSON.parse(await page.locator("#raw").textContent()).objective;
    assert.equal(corrected.fields.target_amount,"250000");assert(corrected.revision>revision);
    assert.equal(corrected.confirmed_revision,null);assert.equal(corrected.readiness,"READY");
    assert(await page.locator("#execute").isDisabled());assert(await page.locator("#plan").isDisabled());
    report.checks.push("B: incomplete objective, missing fields, correction revises brief and invalidates backend confirmation");
    await snap("desktop-correction",1440);
    // Browser transport unavailability: intentionally abort this tab's health request.
    await page.route("**/api/health",route=>route.abort("failed"));
    await click("#refresh");assert.equal(await page.locator("#connection").innerText(),"Services unavailable");
    assert(await page.locator("#send").isDisabled());assert(await page.locator("#execute").isDisabled());
    await snap("disconnected",1440);
    report.checks.push("D browser transport: unavailable health disables actions and shows safe error (request aborted by test; separate real transport test required)");
    report.operations=requests.map(r=>r.operation);report.page_errors=errors;
    assert.equal(errors.length,0);
    report.status="PASS_WITH_LIFECYCLE_AND_REAL_UNAVAILABLE_PENDING";
  }catch(error){report.status="FAILED";report.failure=error.message;report.operations=requests.map(r=>r.operation);fs.writeFileSync(path.join(evidence,"failed-browser-state.json"),await page.locator("#raw").textContent());await page.screenshot({path:path.join(evidence,"browser-failed.png"),fullPage:true});process.exitCode=1;}
  finally{fs.writeFileSync(path.join(evidence,"browser-qa.json"),JSON.stringify(report,null,2));console.log(JSON.stringify(report));await browser.close();}
})().catch(e=>{console.log("BROWSER_QA_UNAVAILABLE "+e.message);process.exit(1);});
