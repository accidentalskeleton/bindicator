"""Self-contained responsive LAN interface: Test Lights and Admin tabs."""
HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bindicator · Local Control</title>
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<style>
:root{color-scheme:dark;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:#0d1720;color:#edf4f7}
*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:26px 20px 65px}
header{position:relative;display:block;margin:0 0 16px}
header .brand-banner{position:relative;isolation:isolate;overflow:hidden;width:100%;border:0;background:#0d1720}
header .brand-banner::after{content:"";position:absolute;pointer-events:none;inset:0;background:linear-gradient(to bottom,#0d1720 0%,transparent 12%,transparent 78%,#0d1720 100%);z-index:1}
header .brand-meta{margin-top:-2px;padding:0 4px 12px;border-bottom:1px solid #273c48}

.brand-meta{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;padding:0 6px}
.brand-meta .small{margin:0}
.brand-logo{width:100%;height:auto;display:block;object-fit:contain;mix-blend-mode:lighten;opacity:.84;filter:saturate(.78) brightness(.9);-webkit-mask-image:linear-gradient(to right,transparent 0%,black 4%,black 96%,transparent 100%);mask-image:linear-gradient(to right,transparent 0%,black 4%,black 96%,transparent 100%)}
.brand-title{width:100%;margin:0}
@media(max-width:600px){header .brand-banner{height:190px}.brand-logo{width:570px;max-width:none;position:relative;left:50%;transform:translateX(-50%)}header .brand-meta{padding:5px 2px 12px}}
h1{margin:0;font-size:2rem;letter-spacing:-.055em}h1 span{color:#7bddae}
h2{font-size:1.2rem;margin:0 0 10px}h3{font-size:1rem;margin:12px 0}
p{color:#b1c3d0;margin:4px 0 16px}.muted,.small{color:#b1c3d0;font-size:.9rem}.tag{border:1px solid #395163;padding:5px 11px;border-radius:22px;font-size:.78rem}
nav{display:flex;flex-wrap:wrap;gap:5px 9px;border-bottom:1px solid #405160;margin-bottom:20px}
nav button{background:transparent;color:#bdcdd6;border:0;border-radius:9px 9px 0 0;padding:13px 17px;white-space:nowrap}
nav button[aria-selected=true]{background:#253c4b;color:#b6f8d6;box-shadow:inset 0 -3px #7bddae}
@media(max-width:600px){nav{gap:4px}nav button{padding:10px 11px;font-size:.9rem}}
.tab[hidden]{display:none}section{background:#1b2a37;border:1px solid #354a59;border-radius:13px;padding:19px;margin-bottom:16px}
.columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(295px,1fr));gap:15px}
button,select,input,textarea{font:inherit}button{background:#7bddae;color:#10291e;border:0;border-radius:8px;padding:9px 14px;font-weight:650;cursor:pointer}
button.secondary{background:#344e60;color:#eef5f8}
.event-groups{display:grid;gap:12px;margin:15px 0}
.event-group{padding:14px;border:1px solid #405566;border-radius:10px;background:#13242f}
.event-group-title{display:flex;align-items:center;gap:9px;font-weight:650;margin-bottom:8px}
.event-picker{border:1px solid #557083;border-radius:8px;background:#172c38;margin-top:8px}
.event-picker>summary{padding:10px 12px;cursor:pointer}
.event-picker-content{padding:10px 12px;max-height:300px;overflow:auto;border-top:1px solid #354a59}
.event-option{display:flex;align-items:flex-start;gap:9px;padding:6px 2px;cursor:pointer}
.event-option[hidden]{display:none}
.event-option span{flex:1;min-width:0;overflow-wrap:anywhere}
.event-option small{color:#a4bdc9;display:block}
.event-chips{display:flex;flex-wrap:wrap;gap:6px}
.event-chip{display:inline-flex;align-items:center;gap:7px;background:#284353;border:1px solid #476177;border-radius:999px;padding:3px 7px 3px 10px;font-size:.84rem}
.event-chip button{padding:0 5px;background:transparent;color:#d3e7f4;border-radius:50%;font-size:1rem}
.event-custom{display:flex;gap:7px;margin-top:10px;flex-wrap:wrap}
.event-custom input{flex:1;min-width:160px}
button.colour-test{display:inline-flex;align-items:center;justify-content:center;gap:9px}
.colour-test-dot{display:inline-block;flex:none;width:12px;height:12px;border-radius:50%;border:1px solid rgba(255,255,255,.4);box-shadow:0 0 0 1px rgba(0,0,0,.22)}button.danger{background:#77434c;color:#fff}
button:disabled{opacity:.55;cursor:wait}
input,select,textarea{background:#101d28;border:1px solid #557083;color:white;border-radius:7px;padding:9px;max-width:100%}
input[type=checkbox]{width:20px;height:20px;accent-color:#7bddae}
input[type=number]{width:105px}input[type=text]{min-width:145px}
.controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.item{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid #304555}.item:first-child{border-top:0}
.field{display:flex;flex-direction:column;gap:5px;margin:8px 0}.field label{font-size:.85rem;color:#c9d7df}
.message{display:none;margin:0 0 17px;padding:11px 14px;border-radius:8px;background:#285240;color:#eafff2}.message.error{background:#65373e;color:#fff}
.editor-row{display:grid;grid-template-columns:minmax(120px,1.5fr) minmax(80px,1fr) auto;gap:9px;padding:7px 0;align-items:center}
.editor-row input{width:100%;min-width:0}.editor-row.colour{grid-template-columns:minmax(90px,1fr) 52px minmax(95px,130px) auto}
.editor-row.colour input[type=color]{width:48px;height:42px;padding:3px;cursor:pointer}
.editor-row.colour details{grid-column:1/-1;background:#11232e;padding:8px 12px;border-radius:7px}
.editor-row.colour details input{width:90px}
.admin-section{background:#1b2a37;border:1px solid #354a59;border-radius:13px;margin-bottom:14px}
.admin-section>summary{list-style:none;cursor:pointer;padding:17px 20px;font-size:1.13rem;font-weight:650;display:flex;align-items:center;justify-content:space-between}
.admin-section>summary::-webkit-details-marker{display:none}
.admin-section>summary::after{content:'+';font-size:1.4rem;color:#7bddae}
.admin-section[open]>summary::after{content:'−'}
.admin-section .detail-content{padding:0 19px 19px}
.main-section>summary{font-size:1.2rem;padding:18px 20px}.main-section .detail-content{padding:0 20px 19px}.main-section[open]>summary{padding-bottom:12px}
.light-group-heading{margin:20px 0 6px;padding:8px 0 5px;border-bottom:1px solid #3b5362;color:#c7dbe4;font-size:.92rem;font-weight:650}
.light-group-heading:first-child{margin-top:9px}
.light-list-divider{height:1px;background:#3b5362;margin:19px 0 15px}
.light-group-label{font-size:.8rem;color:#9fb5c2;text-transform:uppercase;letter-spacing:.055em}
.selection-name{font-weight:650}.selection-meta{font-size:.85rem;color:#a8bfcb;overflow-wrap:anywhere}
.preview-swatch{display:inline-block;width:22px;height:22px;border-radius:6px;border:1px solid #789;vertical-align:middle;margin-right:6px}
.bin-collection-icons{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:10px 0 6px}
.bin-collection-item{display:inline-flex;align-items:center;gap:7px;color:#dce8ed;font-size:.92rem}
.bin-collection-icon{width:39px;height:48px;flex:none;filter:drop-shadow(0 2px 2px rgba(0,0,0,.17))}
.next-collection-date{font-weight:650;color:#eff9fa;line-height:1.4}
.next-collection-colours{font-size:.82rem;color:#a4bdc9;margin-top:5px}
.collection-entry{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid #314958}.collection-entry:first-child{border-top:0}.collection-info{flex:1;min-width:0}.collection-date{font-weight:650}.collection-types{color:#b5c9d4;font-size:.9rem}.collection-colours{font-size:.82rem;color:#a4bdc9}
code{color:#c0e1ee}footer{font-size:.85rem;color:#a9bbca}
@media(max-width:560px){main{padding:14px 12px}section{padding:15px}.editor-row,.editor-row.colour{grid-template-columns:1fr 1fr}.editor-row input:first-child{grid-column:1/-1}}
.savebar{position:sticky;bottom:10px;background:#152a38;border:1px solid #476177;border-radius:12px;padding:12px;margin-top:20px;z-index:5}
.editor-row.colour{grid-template-columns:32px 36px minmax(100px,1fr) 52px minmax(90px,125px) auto}
.editor-row.colour .reorder{cursor:grab;touch-action:none;background:transparent;color:#c5d5dd;padding:5px}
.editor-row.colour .move{padding:5px 9px;min-width:32px}
.editor-row.colour .move-buttons{display:flex;flex-direction:column;gap:3px}
.editor-row.colour.drag-over{outline:2px solid #7bddae;border-radius:8px}
.editor-row.colour details{grid-column:1/-1}
@media(max-width:680px){.editor-row.colour{grid-template-columns:28px 32px minmax(90px,1fr) 45px auto}.editor-row.colour input:nth-of-type(3){grid-column:3/-1}}
.priority-item{gap:12px}.priority-swatch{display:inline-block;width:22px;height:22px;border:1px solid #657b8b;border-radius:5px;flex-shrink:0}.priority-item button{min-width:36px;padding:6px 10px}
.info-panel{max-width:760px}
.help-version{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 16px;border:1px solid #405566;border-radius:9px;background:#172c38;margin:16px 0 24px}
.help-version strong{color:#b6f8d6;font-variant-numeric:tabular-nums}
.help-links{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:12px 0 18px}
.help-links a{display:flex;align-items:center;min-height:44px;padding:11px 13px;border:1px solid #456276;border-radius:8px;background:#213b4b;color:#d8f2e7;text-decoration:none}
.help-links a:hover,.help-links a:focus-visible{background:#30566b;outline-color:#b6f8d6}
.coffee-panel{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:260px;gap:14px;padding:30px 20px;text-align:center}
.coffee-panel h2,.coffee-panel p{margin:0}
.coffee-icon{font-size:44px;line-height:1}
.coffee-button{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:10px 20px;border:1px solid #647f68;border-radius:9px;background:#233e30;color:#e8f2e9;font-weight:650;text-decoration:none}
.coffee-button:hover,.coffee-button:focus-visible{background:#30563c;outline-color:#b6f8d6}
</style></head><body><main>
<header><div class="brand-title"><div class="brand-banner"><img class="brand-logo" src="/static/bindicator-soft-banner.webp" width="1400" height="466" alt="Bindicator" decoding="async"></div></div><div class="brand-meta"><div class="small">Home lighting &amp; bin collection reminders</div><span class="tag">LOCAL NETWORK</span></div></header>
<nav role="tablist" aria-label="Bindicator"><button role="tab" id="tab-status" aria-controls="panel-status" aria-selected="true">Status</button><button role="tab" id="tab-testing" aria-controls="panel-testing" aria-selected="false">Testing</button><button role="tab" id="tab-lighting" aria-controls="panel-lighting" aria-selected="false">Lighting</button><button role="tab" id="tab-colours" aria-controls="panel-colours" aria-selected="false">Colours</button><button role="tab" id="tab-calendars" aria-controls="panel-calendars" aria-selected="false">Calendars</button><button role="tab" id="tab-mapping" aria-controls="panel-mapping" aria-selected="false">Mapping</button><button role="tab" id="tab-help" aria-controls="panel-help" aria-selected="false">Help</button><button role="tab" id="tab-coffee" aria-controls="panel-coffee" aria-selected="false">☕ Coffee</button></nav>
<div id="notice" class="message" role="status"></div>
<div id="panel-status" class="tab" role="tabpanel" aria-labelledby="tab-status">
<div class="columns"><section><h2>Next collection</h2><div id="next" class="muted">Loading…</div><button id="refresh" class="secondary" style="margin-top:13px">Refresh</button></section>
<section><h2>Reminder status</h2><div id="status" class="muted">Loading…</div><div class="controls" style="margin-top:13px">
<button id="pause" class="secondary">Pause</button><button id="resume" class="secondary">Resume</button><button id="toggle" class="secondary">Toggle</button></div></section></div>
<details class="admin-section main-section" id="next-collection-section" open><summary>Next collection alerts</summary><div class="detail-content"><p>Upcoming collection days from the active source. Test each day's actual indicator colours for 10 seconds; previous light states are restored where safe.</p>
<div id="councilstatus" class="small" role="status" hidden></div>
<div id="upcoming" aria-live="polite">Loading upcoming collections…</div>
<div class="controls" style="margin-top:14px"><button id="upcomingrefresh" class="secondary">Refresh collections</button><button id="nextpersistent" class="danger">Activate next collection until collection morning</button></div></div></details>
</div>
<div id="panel-testing" class="tab" role="tabpanel" aria-labelledby="tab-testing" hidden>
<details class="admin-section main-section" id="test-indicator-section" open><summary>Test indicator colours</summary><div class="detail-content"><p>Preview colours on your configured lamps. The original lamp state is restored where unchanged. Tests are refused if reminders are paused or an alert is already active.</p>
<div class="controls"><label for="testseconds">Duration</label><select id="testseconds"><option value="5">5 seconds</option><option value="10">10 seconds</option><option value="20">20 seconds</option><option value="30">30 seconds</option></select></div>
<div id="quicktests" class="controls" style="margin-top:15px"></div>
</div></details>
</div>
<div id="panel-lighting" class="tab" role="tabpanel" aria-labelledby="tab-lighting" hidden>
<details class="admin-section"><summary>Hue Bridges</summary><div class="detail-content">
<p>Discover Bridges via mDNS and pair by pressing each Bridge's physical link button.</p>
<div id="bridges"></div><button id="discover" class="secondary">Discover Bridges</button><div id="discoveredbridges"></div>
</div></details>
<details class="admin-section"><summary>Indicator lights</summary><div class="detail-content">
<h3>Currently selected</h3><div id="selectedlights" aria-live="polite">Loading configured lights…</div>
<div class="light-list-divider" role="separator" aria-label="Available lights"></div><h3>Available lights by Hue Bridge</h3>
<p>Select a light to briefly flash it for identification, or use its Identify button at any time. Previous appearance is restored where safe. Saved lamp IDs remain visible if a Bridge is offline. Gradient-capable lamps can be set to <b>Always multi-colour</b>, overriding Priority mode for that lamp only.</p>
<div class="controls"><button id="scanlights" class="secondary">Refresh available lights</button><button id="savelights">Save selected lights</button></div>
<div id="lights"></div></div></details>
<details class="admin-section"><summary>Reminder timing</summary><div class="detail-content">
<p>Times are in Europe/London (automatically following GMT/BST). Choose when lights change on the <b>day before</b> collection and when they are restored on collection morning.</p>
<div class="controls"><label for="starttime">Activate the evening before</label><input id="starttime" type="time" min="12:00" max="23:59" step="60">
<label for="restoretime">Restore on collection day</label><input id="restoretime" type="time" min="00:00" max="11:59" step="60">
<button id="saveschedule">Save times</button></div><p class="small">Default: 18:00 activation, 09:00 restoration. Changes take effect on the next schedule check (within a minute).</p>
</div></details>
<details class="admin-section"><summary>Display settings</summary><div class="detail-content">
<p>For lamps that display only one colour, Cycle rotates through each collection colour every minute. Manual lamp changes are respected.</p><div class="controls"><label for="mode">Colour mode</label><select id="mode"><option value="spread">Spread across lamps</option><option value="priority">Highest priority on every lamp</option><option value="cycle">Cycle through collection colours (one per minute)</option></select><button id="savemode">Save mode</button></div>
</div></details>

</div>
<div id="panel-colours" class="tab" role="tabpanel" aria-labelledby="tab-colours" hidden>
<details class="admin-section"><summary>Indicator colours</summary><div class="detail-content">
<p>Define up to five indicator colours. Reorder them with the arrows or drag handles; the first has highest priority. Choose a swatch to edit its colour. Changes to colours and mappings are saved together.</p><h3>Bin colours <span id="colourcount" class="small"></span></h3>
<div id="colourrows" aria-label="Colours, highest priority first"></div><div class="controls"><button id="addcolour" class="secondary">+ Add colour</button></div>
<div class="savebar controls"><span id="dirtyhintcolours" class="small" role="status">No unsaved changes</span><button id="discardcoloursection" class="secondary">Discard</button><button id="savecoloursection">Save changes</button></div>
<div id="priorityrows" hidden aria-label="Colour priority order"></div><button id="savepriority" hidden>Save priority</button>
</div></details>
</div>
<div id="panel-calendars" class="tab" role="tabpanel" aria-labelledby="tab-calendars" hidden>
<section>
<h2>Active calendar source</h2>
<p>Choose which configured calendar supplies collection dates to Status, Hue reminders and Alexa.</p>
<div class="controls"><label for="activesource">Active source</label>
<select id="activesource"><option value="ical">iCalendar (iCal)</option><option value="council">North Yorkshire Council</option></select>
<button id="savesource">Save active source</button></div>
<div class="controls"><label for="calendarinterval">Automatic refresh interval (days)</label>
<input id="calendarinterval" type="number" min="1" max="90" value="7" step="1">
<button id="saveinterval" class="secondary">Save interval</button></div>
<div class="controls"><button id="refreshactive" class="secondary">Refresh active calendar now</button></div>
<p id="activecalendarstate" class="small" role="status">Checking active source…</p>
<p id="activecalendarupdated" class="small" role="status"></p>
</section>
<details class="admin-section"><summary>North Yorkshire Council</summary><div class="detail-content">
<p>Use the council's read-only collection lookup. The property's UPRN is stored locally and never displayed again.</p>
<p id="councilstate" class="small">Checking council source…</p>
<div class="field"><label for="counciluprn">Property UPRN</label><input id="counciluprn" type="password" inputmode="numeric" autocomplete="off" placeholder="Leave blank to retain saved UPRN"></div>
<div id="councilupdated" class="small" role="status"></div>
<div class="controls"><button id="savecouncil">Save council settings</button>
<button id="counciltest" class="secondary">Test access</button>
<button id="councilpreview" class="secondary">Preview dates</button></div>
<div id="councilresults" aria-live="polite" class="small"></div>
</div></details>
<details class="admin-section"><summary>iCalendar (iCal)</summary><div class="detail-content">
<p>Connect any supported public HTTPS iCalendar feed, including Zoho, Google Calendar or Outlook. The private URL stays on this device and is never returned by the API.</p>
<p id="calendarstate" class="small">Checking iCalendar configuration…</p>
<div class="field"><label for="calendarurl">Private iCalendar URL (leave blank to keep existing)</label>
<input type="password" id="calendarurl" autocomplete="off" placeholder="https://calendar.example.com/private-feed.ics"></div>
<div class="controls"><button id="savecalendar">Save iCalendar URL</button>
<button id="icaltest" class="secondary">Test access</button>
<button id="icalpreview" class="secondary">Preview dates</button></div>
<div id="icalresults" aria-live="polite" class="small"></div>
</div></details>
</div>
<div id="panel-mapping" class="tab" role="tabpanel" aria-labelledby="tab-mapping" hidden>
<details class="admin-section"><summary>Calendar event mappings</summary><div class="detail-content">
<p>Choose multiple event titles for each colour. Search events from your configured Zoho and North Yorkshire Council sources, or add a custom title. Each title can belong to one colour. Changes are saved together with colour settings.</p>
<div class="controls"><button id="refreshevents" class="secondary">Refresh calendar events</button><span id="eventsourcehint" class="small" role="status">Discovering available event titles…</span></div>
<div id="eventrows" class="event-groups"></div><div class="savebar controls"><span id="dirtyhint" class="small" role="status">No unsaved changes</span><button id="discardcolours" class="secondary">Discard</button><button id="savecolours">Save changes</button></div><button id="saveevents" hidden>Save mappings</button>
</div></details>
</div>
<div id="panel-help" class="tab" role="tabpanel" aria-labelledby="tab-help" hidden>
<section class="info-panel">
<h2>Help &amp; project information</h2>
<p>Bindicator is a self-hosted bin collection reminder for Philips Hue lights.</p>
<div class="help-version"><span>Installed Bindicator version</span><strong id="bindicatorversion">Loading…</strong></div>
<h3>Documentation and support</h3>
<div class="help-links">
<a href="https://github.com/accidentalskeleton/bindicator" target="_blank" rel="noopener noreferrer">GitHub project</a>
<a href="https://github.com/accidentalskeleton/bindicator/blob/main/README.md" target="_blank" rel="noopener noreferrer">Getting started</a>
<a href="https://github.com/accidentalskeleton/bindicator/blob/main/docs/README.md" target="_blank" rel="noopener noreferrer">Documentation</a>
<a href="https://github.com/accidentalskeleton/bindicator/blob/main/docs/calendar-providers.md" target="_blank" rel="noopener noreferrer">Adding a calendar provider</a>
<a href="https://github.com/accidentalskeleton/bindicator/issues" target="_blank" rel="noopener noreferrer">Report a problem or suggest a feature</a>
<a href="https://github.com/accidentalskeleton/bindicator/releases" target="_blank" rel="noopener noreferrer">Releases</a>
</div>
<p class="small">The version shown is the installed Python package version. Updates and source revisions are available on GitHub.</p>
</section>
</div>
<div id="panel-coffee" class="tab" role="tabpanel" aria-labelledby="tab-coffee" hidden>
<section class="coffee-panel">
<div class="coffee-icon" aria-hidden="true">☕</div>
<h2>Enjoying Bindicator?</h2>
<p>If you'd like to support its development, you can buy me a coffee.</p>
<a class="coffee-button" href="https://buymeacoffee.com/stuliet" target="_blank" rel="noopener noreferrer">☕ Buy me a coffee</a>
</section>
</div>
<footer>Accessible only on the explicitly configured LAN interface. Keep port 18051 off Cloudflare Tunnel and the public internet.</footer>
</main><script>
const $=id=>document.getElementById(id);
const node=(tag,text="",className="")=>{const e=document.createElement(tag);e.textContent=text;if(className)e.className=className;return e;};
function notice(msg,bad=false){let n=$("notice");n.textContent=msg;n.className="message"+(bad?" error":"");n.style.display="block";}
let autoScanned=false,mappingLoaded=false,currentActiveSource="ical",councilLegacyRefreshDays=7;
function openTab(name){for(const n of ["status","testing","lighting","colours","calendars","mapping","help","coffee"]){$("tab-"+n).setAttribute("aria-selected",n===name?"true":"false");$("panel-"+n).hidden=n!==name;}
 if(name==="lighting"&&!autoScanned){autoScanned=true;$("scanlights").click();}
 if(name==="mapping"&&!mappingLoaded){mappingLoaded=true;refreshCalendarEventOptions();}
 if(name==="testing")refreshTestColours();
}
$("tab-status").onclick=()=>openTab("status");$("tab-testing").onclick=()=>openTab("testing");$("tab-lighting").onclick=()=>openTab("lighting");$("tab-colours").onclick=()=>openTab("colours");$("tab-calendars").onclick=()=>openTab("calendars");$("tab-mapping").onclick=()=>openTab("mapping");$("tab-help").onclick=()=>openTab("help");$("tab-coffee").onclick=()=>openTab("coffee");
async function request(url,body){const init={credentials:"same-origin",headers:{}};
 if(body!==undefined){init.method="POST";init.headers={"Content-Type":"application/json","X-Bindicator-Request":"management"};init.body=JSON.stringify(body);}
 const res=await fetch(url,init);const j=await res.json();if(!res.ok)throw Error(j.error||"HTTP "+res.status);return j.data===undefined?j:j.data;}
function run(id,fn){const b=$(id);b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){notice(e.message,true);}finally{b.disabled=false;}};}
function inp(value,type="text"){const e=document.createElement("input");e.type=type;e.value=String(value);return e;}
// sRGB <-> CIE xy (D65, linear-light matrix). Existing xy is preserved
// exactly until the user edits the picker, HEX or advanced coordinates.
const clamp=(v,min=0,max=1)=>Math.min(max,Math.max(min,v));
function rgbToXY(hex){
 if(!/^#[0-9a-f]{6}$/i.test(hex))throw Error("Use a six-digit HEX colour.");
 const values=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
 const [r,g,b]=values.map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
 const X=0.4124564*r+0.3575761*g+0.1804375*b;
 const Y=0.2126729*r+0.7151522*g+0.0721750*b;
 const Z=0.0193339*r+0.1191920*g+0.9503041*b;
 const sum=X+Y+Z;if(sum<1e-10)throw Error("Pure black has no chromaticity; choose a non-black colour.");
 return {x:Number((X/sum).toFixed(6)),y:Number((Y/sum).toFixed(6))};
}
function xyToHex(xy){
 const x=Number(xy.x),y=Number(xy.y);
 if(!(x>0&&y>0&&x+y<1))return "#ffffff";
 const X=x/y,Y=1,Z=(1-x-y)/y;
 let rgb=[3.2404542*X-1.5371385*Y-0.4985314*Z,
          -0.9692660*X+1.8760108*Y+0.0415560*Z,
          0.0556434*X-0.2040259*Y+1.0572252*Z];
 // Normalise out-of-gamut values for a representative screen swatch.
 rgb=rgb.map(v=>Math.max(0,v));const max=Math.max(...rgb,1e-10);rgb=rgb.map(v=>v/max);
 const srgb=rgb.map(v=>v<=0.0031308?12.92*v:1.055*(v**(1/2.4))-0.055);
 return "#"+srgb.map(v=>Math.round(clamp(v)*255).toString(16).padStart(2,"0")).join("");
}
function addColour(name="",xy={x:0.3,y:0.3}){
 const r=node("div","","editor-row colour"), nameInput=inp(name);
 const picker=inp(xyToHex(xy),"color"), hexInput=inp(picker.value);
 hexInput.maxLength=7;hexInput.setAttribute("aria-label","RGB HEX colour");
 const advanced=document.createElement("details"),summary=node("summary","Advanced: Hue CIE xy");
 advanced.append(summary);const coordinates=node("div","","controls"),x=inp(xy.x,"number"),y=inp(xy.y,"number");
 x.step=y.step="0.000001";x.min=y.min="0";x.max=y.max="1";
 coordinates.append(node("label","x"),x,node("label","y"),y);advanced.append(coordinates);
 r.dataset.originalX=String(xy.x);r.dataset.originalY=String(xy.y);
 r.dataset.originalHex=picker.value.toUpperCase();
 r.dataset.originalName=name;r.dataset.priorityName=name;
 const setHex=value=>{if(!/^#[0-9a-f]{6}$/i.test(value))return;
  picker.value=value.toLowerCase();hexInput.value=value.toUpperCase();
  const converted=rgbToXY(value);x.value=converted.x;y.value=converted.y;r.dataset.edited="rgb";};
 picker.oninput=()=>{setHex(picker.value);syncPriorityFromEditor();};hexInput.oninput=()=>{if(!/^#[0-9a-f]{6}$/i.test(hexInput.value)){notice("Invalid RGB HEX colour.",true);return;}setHex(hexInput.value);syncPriorityFromEditor();};
 const updateAdvanced=()=>{if(!(Number(x.value)>0&&Number(y.value)>0&&Number(x.value)+Number(y.value)<1))return;
  const next=xyToHex({x:Number(x.value),y:Number(y.value)});picker.value=next;hexInput.value=next.toUpperCase();r.dataset.edited="xy";syncPriorityFromEditor();};
 x.onchange=updateAdvanced;y.onchange=updateAdvanced;
 const del=node("button","Remove","secondary");del.onclick=()=>{r.remove();syncPriorityFromEditor();syncEventChoices();markDirty();};
 nameInput.oninput=()=>{syncPriorityFromEditor();syncEventChoices();markDirty();};
 const handle=node("span","⋮⋮","reorder");handle.draggable=true;handle.title="Drag to change priority";handle.setAttribute("aria-label","Drag colour to reorder");
 const moves=node("div","","move-buttons"),up=node("button","↑","secondary move"),down=node("button","↓","secondary move");
 up.type=down.type="button";up.title="Move up";down.title="Move down";
 up.onclick=()=>shiftColour(r,-1);down.onclick=()=>shiftColour(r,1);moves.append(up,down);
 handle.addEventListener("dragstart",e=>{dragColour=r;e.dataTransfer.effectAllowed="move";});
 handle.addEventListener("dragend",()=>{dragColour=null;r.classList.remove("drag-over");});
 r.addEventListener("dragover",e=>{if(dragColour&&dragColour!==r){e.preventDefault();r.classList.add("drag-over");}});
 r.addEventListener("dragleave",()=>r.classList.remove("drag-over"));
 r.addEventListener("drop",e=>{e.preventDefault();r.classList.remove("drag-over");if(dragColour&&dragColour!==r){r.before(dragColour);syncOrderFromRows();markDirty();}});
 r.append(handle,moves,nameInput,picker,hexInput,del,advanced);$("colourrows").append(r);
 r.addEventListener("input",markDirty);r.addEventListener("change",markDirty);
 refreshColourCount();
}
let eventAssignments={};
let availableCalendarEvents=[];
function eventColourName(saved){
 const row=[...$("colourrows").children].find(r=>r.dataset.originalName===saved);
 return row?row.children[2].value.trim():saved;
}
function renderEventMappings(openColour=null){
 const parent=$("eventrows");
 if(!openColour){
  const current=parent.querySelector(".event-group details[open]");
  openColour=current?.closest(".event-group")?.dataset.colour||null;
 }
 parent.replaceChildren();
 const colours=activeColours();
 for(const colour of colours){
  const group=node("div","","event-group");group.dataset.colour=colour;
  const heading=node("div","","event-group-title");
  const dot=node("span","","colour-test-dot");
  dot.setAttribute("aria-hidden","true");
  const row=[...$("colourrows").children].find(r=>r.children[2].value.trim()===colour);
  dot.style.backgroundColor=row?row.children[3].value:xyToHex(priorityPalette[colour]||{x:.3,y:.3});
  heading.append(dot,node("span",colour));
  const selected=Object.keys(eventAssignments).filter(title=>eventColourName(eventAssignments[title])===colour);
  const chips=node("div","","event-chips");
  for(const title of selected.sort(alphabetical)){
   const chip=node("span","","event-chip");
   const remove=node("button","×");
   remove.type="button";remove.setAttribute("aria-label","Unmap "+title+" from "+colour);
   remove.onclick=()=>{delete eventAssignments[title];markDirty();renderEventMappings(colour);};
   chip.append(node("span",title),remove);chips.append(chip);
  }
  const picker=document.createElement("details");picker.className="event-picker";
  picker.open=openColour===colour;
  const summary=node("summary","Select events ("+selected.length+")");
  const content=node("div","","event-picker-content");
  const search=inp("");search.placeholder="Search available calendar events";
  search.setAttribute("aria-label","Search calendar events for "+colour);
  const options=node("div","","event-options");
  const titles=new Map(availableCalendarEvents.map(e=>[e.title,e.sources]));
  for(const title of Object.keys(eventAssignments))if(!titles.has(title))titles.set(title,["Saved mapping"]);
  for(const [title,sources] of [...titles].sort((a,b)=>alphabetical(a[0],b[0]))){
   const label=document.createElement("label");label.className="event-option";
   const check=inp("","checkbox");check.checked=eventColourName(eventAssignments[title])===colour;
   check.setAttribute("aria-label","Map "+title+" to "+colour);
   const detail=node("span");detail.append(node("span",title));
   detail.append(node("small",sources.join(" · ")));
   check.onchange=()=>{
    if(check.checked)eventAssignments[title]=colour;
    else if(eventColourName(eventAssignments[title])===colour)delete eventAssignments[title];
    markDirty();renderEventMappings(colour);
   };
   label.append(check,detail);options.append(label);
  }
  search.oninput=()=>{
   const query=search.value.trim().toLocaleLowerCase();
   for(const label of options.children)label.hidden=!label.textContent.toLocaleLowerCase().includes(query);
  };
  const custom=node("div","","event-custom");
  const customTitle=inp("");customTitle.placeholder="Custom event title";
  customTitle.setAttribute("aria-label","Custom event title for "+colour);
  const add=node("button","Add event","secondary");add.type="button";
  add.onclick=()=>{
   const title=customTitle.value.trim();
   if(!title||title.length>120){notice("Enter an event title of 1–120 characters.",true);return;}
   eventAssignments[title]=colour;
   if(!availableCalendarEvents.some(e=>e.title===title))
    availableCalendarEvents.push({title,sources:["Custom"]});
   markDirty();renderEventMappings(colour);
  };
  custom.append(customTitle,add);
  content.append(search,options,custom);
  picker.append(summary,content);
  group.append(heading,chips,picker);parent.append(group);
 }
}
async function refreshCalendarEventOptions(){
 try{
  const result=await request("/manage/calendar-events");
  availableCalendarEvents=result.events;
  $("eventsourcehint").textContent=result.warnings.length
   ?result.warnings.join("; ")+" — saved mappings remain available."
   :result.events.length+" event titles available from configured sources.";
  renderEventMappings();
 }catch(e){$("eventsourcehint").textContent="Could not discover calendar events; saved mappings remain available.";renderEventMappings();}
}
let dragColour=null,loadingEditor=false,dirty=false;
function markDirty(){if(loadingEditor)return;dirty=true;for(const id of ["dirtyhint","dirtyhintcolours"])$(id).textContent="Unsaved changes";}
function refreshColourCount(){const count=$("colourrows").children.length;$("colourcount").textContent=count+"/5";$("addcolour").disabled=count>=5;}
function shiftColour(row,delta){const sibling=delta<0?row.previousElementSibling:row.nextElementSibling;if(!sibling)return;
 if(delta<0)sibling.before(row);else sibling.after(row);syncOrderFromRows();markDirty();}
function syncOrderFromRows(){priorityOrder=[...$("colourrows").children].map(r=>r.children[2].value.trim());renderPriority();refreshColourCount();}
function syncEventChoices(){renderEventMappings();}
let priorityOrder=[];
let priorityPalette={};
function renderPriority(){
 const parent=$("priorityrows");parent.replaceChildren();
 for(const [index,name] of priorityOrder.entries()){
  const row=node("div","","item priority-item"),detail=node("div","","controls");
  const swatch=node("span","","priority-swatch");
  swatch.style.backgroundColor=xyToHex(priorityPalette[name]||{x:0.33,y:0.33});
  swatch.setAttribute("aria-hidden","true");
  detail.append(node("strong",(index+1)+". "+name),swatch);
  const actions=node("div","","controls");
  const up=node("button","↑","secondary"),down=node("button","↓","secondary");
  up.type=down.type="button";
  up.disabled=index===0;down.disabled=index===priorityOrder.length-1;
  up.setAttribute("aria-label","Move "+name+" up");
  down.setAttribute("aria-label","Move "+name+" down");
  up.onclick=()=>movePriority(index,-1);
  down.onclick=()=>movePriority(index,1);
  actions.append(up,down);row.append(detail,actions);parent.append(row);
 }
}
function movePriority(index,direction){
 const next=index+direction;
 if(next<0||next>=priorityOrder.length)return;
 [priorityOrder[index],priorityOrder[next]]=[priorityOrder[next],priorityOrder[index]];
 renderPriority();
 const controls=$("priorityrows").children[next]?.querySelectorAll("button");
 if(controls)controls[direction<0?0:1].focus();
}
function syncPriorityFromEditor(){
 const rows=[...$("colourrows").children];
 const palette={}, seen=new Set();
 for(const row of rows){
  const name=row.children[2].value.trim(),old=row.dataset.priorityName;
  // Keep the old priority position while the user is partway through
  // editing a name (e.g. temporarily blank). A removed row is different:
  // its old name is no longer present and is dropped from the list.
  if(!/^[a-z][a-z0-9_]{0,31}$/.test(name)||seen.has(name)){
   if(old)seen.add(old);
   continue;
  }
  seen.add(name);
  const position=priorityOrder.indexOf(old);
  if(position!==-1 && old!==name && !priorityOrder.includes(name))priorityOrder[position]=name;
  row.dataset.priorityName=name;
  const advanced=row.querySelectorAll("details input");
  const xy=row.dataset.edited==="xy"
    ?{x:Number(advanced[0].value),y:Number(advanced[1].value)}
    :(/^#[0-9a-f]{6}$/i.test(row.children[4].value)
      ?rgbToXY(row.children[4].value):null);
  if(xy&&Number.isFinite(xy.x)&&Number.isFinite(xy.y)&&xy.x>0&&xy.y>0&&xy.x+xy.y<1)palette[name]=xy;
 }
 priorityOrder=priorityOrder.filter(name=>seen.has(name));
 for(const row of rows){
  const name=row.children[2].value.trim();
  if(seen.has(name)&&!priorityOrder.includes(name))priorityOrder.push(name);
 }
 priorityPalette=palette;
 renderPriority();
}
function activeColours(){return [...$("colourrows").children].map(r=>r.children[2].value.trim()).filter(Boolean);}
const alphabetical=(a,b)=>String(a).localeCompare(String(b),undefined,{sensitivity:"base",numeric:true});
function showSelected(selected,available=[]){
 const target=$("selectedlights");target.replaceChildren();
 if(!selected.length){target.append(node("p","No lights selected yet."));return;}
 const labels=new Map(available.map(x=>[x.bridge+"/"+x.id,x]));
 selected.map((item,i)=>({item,position:i+1,name:labels.get(item.bridge+"/"+item.id)?.name||"Light "+item.id}))
  .sort((a,b)=>alphabetical(a.name,b.name)||alphabetical(a.item.bridge,b.item.bridge)||alphabetical(a.item.id,b.item.id))
  .forEach(({item,position,name})=>{
  const key=item.bridge+"/"+item.id,x=labels.get(key),row=node("div","","item"),info=node("div");
  info.append(node("div",name,"selection-name"));
  info.append(node("div",item.bridge+" · "+(x?x.capability+" · ":"")+"ID: "+item.id+" · Priority "+position+(item.always_gradient?" · Multi-colour always":""),"selection-meta"));
  row.append(info,node("span",x?"Selected":"Configured","small"));target.append(row);
 });
}
function renderConfiguredBridges(bridges){
 const box=$("bridges");box.replaceChildren();
 if(!bridges.length){box.append(node("p","No Hue Bridges configured."));return;}
 for(const bridge of [...bridges].sort((a,b)=>alphabetical(a.name,b.name))){
  const row=node("div","","item"),info=node("div"),actions=node("div","","controls");
  info.append(node("strong",bridge.name),node("div",bridge.host+" · "+(bridge.paired?"Paired":"Not paired"),"small"));
  const del=node("button","Delete","danger");del.type="button";
  del.setAttribute("aria-label","Delete Hue Bridge "+bridge.name);
  del.onclick=async()=>{
   const total=configuredLights.filter(x=>x.bridge===bridge.name).length;
   if(!confirm("Remove Hue Bridge '"+bridge.name+"' from Bindicator and forget its "+total+
    " selected indicator light(s) and saved application key? This does not delete physical Hue lights."))return;
   del.disabled=true;
   try{
    const result=await request("/manage/bridges/delete",{name:bridge.name});
    // Stale lamp discovery results must not show the deleted Bridge.
    lamps=lamps.filter(x=>x.bridge!==bridge.name);
    configuredLights=configuredLights.filter(x=>x.bridge!==bridge.name);
    showSelected(configuredLights,lamps);
    $("lights").replaceChildren(node("p","Refresh available lights to update this list."));
    await refresh();
    notice(result.message||"Hue Bridge removed.");
   }catch(e){notice("Could not delete Hue Bridge: "+e.message,true);}
   finally{del.disabled=false;}
  };
  actions.append(del);row.append(info,actions);box.append(row);
 }
}
// A small set of original wheelie-bin illustrations in the council calendar's
// spirit, drawn as SVG so they stay crisp on Retina and mobile screens.
function binCategory(title){
 const name=String(title).toLocaleLowerCase();
 if(/garden|green waste/.test(name))return "garden";
 if(/recycl|paper|cardboard|glass|plastic|cans/.test(name))return "recycling";
 if(/household|refuse|general waste|rubbish|residual|black bin/.test(name))return "household";
 return "other";
}
function binCollectionIcon(title){
 const kind=binCategory(title);
 const palette={garden:["#4e8855","#305e3c"],recycling:["#4088af","#205773"],household:["#566570","#2d3b44"],other:["#627680","#3f505b"]};
 const [fill,dark]=palette[kind];
 const ns="http://www.w3.org/2000/svg";
 const svg=document.createElementNS(ns,"svg");
 svg.setAttribute("viewBox","0 0 42 54");svg.setAttribute("class","bin-collection-icon");
 svg.setAttribute("aria-hidden","true");svg.setAttribute("focusable","false");
 function shape(tag,attrs){
  const el=document.createElementNS(ns,tag);
  for(const [key,value] of Object.entries(attrs))el.setAttribute(key,String(value));
  svg.append(el);return el;
 }
 shape("path",{d:"M7 11H35L32 45Q21 48 10 45Z",fill,stroke:dark,"stroke-width":"1.5","stroke-linejoin":"round"});
 shape("rect",{x:4,y:7,width:34,height:6,rx:2,fill:dark});
 shape("path",{d:"M10 7V5Q10 3 13 3H29Q32 3 32 5V7",fill:"none",stroke:fill,"stroke-width":2});
 shape("rect",{x:10,y:45,width:5,height:6,rx:2,fill:"#15222b"});
 shape("rect",{x:27,y:45,width:5,height:6,rx:2,fill:"#15222b"});
 shape("path",{d:"M11 15L14 42M30 15L27 42",fill:"none",stroke:"#ffffff","stroke-opacity":".15","stroke-width":1.2});
 if(kind==="recycling"){
  shape("path",{d:"M21 20L25 26H22M26 29L23 35L21 32M19 35H14L17 30M15 28L18 23L20 26",fill:"none",stroke:"#e7f9fc","stroke-width":2.2,"stroke-linecap":"round","stroke-linejoin":"round"});
 }else if(kind==="garden"){
  shape("path",{d:"M16 35Q10 25 26 21Q31 30 20 35Z",fill:"#c8e8bf"});
  shape("path",{d:"M16 37Q20 28 26 24",fill:"none",stroke:dark,"stroke-width":1.5,"stroke-linecap":"round"});
 }else if(kind==="household"){
  shape("path",{d:"M15 23V35M21 21V35M27 23V35",stroke:"#d2dfe4","stroke-width":2.3,"stroke-linecap":"round"});
  shape("path",{d:"M13 21H29",stroke:"#d2dfe4","stroke-width":2,"stroke-linecap":"round"});
 }else{
  shape("path",{d:"M21 23V31M21 35V36",stroke:"#ebf2f6","stroke-width":3,"stroke-linecap":"round"});
 }
 return svg;
}
function collectionIcons(collections){
 const group=node("div","","bin-collection-icons");
 for(const title of collections){
  const item=node("span","","bin-collection-item");
  item.append(binCollectionIcon(title),node("span",title));
  group.append(item);
 }
 return group;
}
function renderNextCollection(upcoming){
 const box=$("next");box.replaceChildren();
 if(!upcoming.length){box.append(node("p","No upcoming collection found.","muted"));return;}
 const item=upcoming[0];
 const dateText=item.weekday+", "+item.date;
 box.append(node("div",dateText,"next-collection-date"));
 box.append(collectionIcons(item.collections));
 box.append(node("div","Colours: "+(item.display_colours||item.colours).join(", "),"next-collection-colours"));
}
function renderUpcoming(collections){
 const list=$("upcoming");list.replaceChildren();
 if(!collections.length){list.append(node("p","No matching collections in the next 365 days."));return;}
 const formatter=new Intl.DateTimeFormat("en-GB",{weekday:"short",day:"numeric",month:"short",year:"numeric",timeZone:"UTC"});
 for(const item of collections){
  const label=formatter.format(new Date(item.date+"T12:00:00Z"));
  const row=node("div","","collection-entry"),info=node("div","","collection-info");
  info.append(node("div",label,"collection-date"),
    collectionIcons(item.collections),
    node("div","Colours: "+(item.display_colours||item.colours).join(", "),"collection-colours"));
  const btn=node("button","Test 10s","secondary");btn.type="button";
  btn.setAttribute("aria-label","Test collection on "+label);
  btn.onclick=async()=>{btn.disabled=true;btn.textContent="Testing…";
   try{notice("Testing collection on "+label+"…");
    const result=await request("/manage/collections/test",{date:item.date,seconds:10});
    notice(result.message||"Collection test finished.");}
   catch(e){notice("Collection test failed: "+e.message,true);}
   finally{btn.disabled=false;btn.textContent="Test 10s";}};
  row.append(info,btn);list.append(row);
 }
}
let lamps=[];let configuredLights=[];
async function refresh(){try{const [v,upcoming]=await Promise.all([request("/manage/overview"),request("/manage/upcoming")]);
 renderUpcoming(upcoming);
 $("bindicatorversion").textContent=v.application_version||"unknown";
 const s=v.status;$("status").textContent=(s.paused?"Paused":"Active")+" · "+s.indicator_count+" active indicator(s)";
 renderNextCollection(upcoming);
 $("mode").value=v.mode;priorityOrder=[...v.priority];priorityPalette=v.colour_xy;renderPriority();
 $("starttime").value=v.schedule.start;$("restoretime").value=v.schedule.restore;
 configuredLights=v.selected;showSelected(configuredLights,lamps);
 $("calendarstate").textContent=v.calendar_configured?"Private iCalendar URL configured.":"No private iCalendar URL configured.";
 $("councilstate").textContent=v.north_yorkshire.configured?"UPRN saved locally.":"No council UPRN configured.";
 currentActiveSource=v.active_calendar_source;
 councilLegacyRefreshDays=v.north_yorkshire.refresh_days;
 const sourceSelect=$("activesource");
 sourceSelect.replaceChildren();
 for(const provider of v.calendar_providers){
  const option=node("option",provider.name);option.value=provider.id;
  option.disabled=!provider.configured&&provider.id!==v.active_calendar_source;
  sourceSelect.append(option);
 }
 sourceSelect.value=v.active_calendar_source;
 $("calendarinterval").value=v.calendar_refresh_days;
 const active=v.active_calendar_source==="council"?v.north_yorkshire:v.ical;
 const dateFormat=value=>value?new Date(value).toLocaleString("en-GB"):"Never";
 $("activecalendarstate").textContent="Active: "+(v.active_calendar_source==="council"?"North Yorkshire Council":"iCalendar")+(active.stale?" · Refresh due":" · Up to date");
 $("activecalendarupdated").textContent="Last successful refresh: "+dateFormat(active.last_success)+" · Next due: "+(active.next_due?dateFormat(active.next_due):"After first successful update");
 $("councilupdated").textContent="Council last updated: "+dateFormat(v.north_yorkshire.last_success);
 renderTestColours(v.colours,v.colour_xy);
 loadingEditor=true;$("colourrows").replaceChildren();for(const name of v.priority)addColour(name,v.colour_xy[name]);
 eventAssignments=Object.fromEntries(v.events.map(e=>[e.name,e.colour]));
 renderEventMappings();
 loadingEditor=false;dirty=false;for(const id of ["dirtyhint","dirtyhintcolours"])$(id).textContent="No unsaved changes";refreshColourCount();
 renderConfiguredBridges(v.bridges);
 }catch(e){notice(e.message,true);}}
function renderTestColours(colours,palette){
 const target=$("quicktests");target.replaceChildren();
 for(const colour of colours){
  const btn=node("button","","secondary colour-test");btn.type="button";
  btn.setAttribute("aria-label","Test "+colour+" indicator colour");
  const dot=node("span","","colour-test-dot");dot.setAttribute("aria-hidden","true");
  dot.style.backgroundColor=xyToHex(palette[colour]);
  btn.append(dot,node("span","Test "+colour));
  btn.onclick=()=>previewColour(colour,btn);target.append(btn);
 }
 if(!colours.length)target.append(node("p","No indicator colours are configured."));
}
async function refreshTestColours(){
 try{const overview=await request("/manage/overview");renderTestColours(overview.colours,overview.colour_xy);}
 catch(e){notice("Could not load indicator colours: "+e.message,true);}
}
async function previewColour(colour,btn){btn.disabled=true;
 try{const seconds=Number($("testseconds").value);notice("Previewing "+colour+" for "+seconds+" seconds…");
 const r=await request("/manage/preview",{colour,seconds});notice(r.message);}catch(e){notice(e.message,true);}finally{btn.disabled=false;}}
for(const action of ["pause","resume","toggle"]){run(action,async()=>{const r=await request("/manage/"+action,{});notice(r.message||action+" complete.");await refresh();});}
run("nextpersistent",async()=>{if(!confirm("Activate the next collection until the configured morning restoration time?"))return;
 const r=await request("/manage/alerts/next",{});notice(r.message||"Reminder activated.");await refresh();});
run("refresh",refresh);
run("upcomingrefresh",refresh);
run("discover",async()=>{const box=$("discoveredbridges");box.replaceChildren(node("p","Discovering Hue Bridges…"));
 const bridges=await request("/manage/discovery");box.replaceChildren();
 if(!bridges.length){box.append(node("p","No Hue Bridges discovered."));return;}
 for(const x of bridges){const row=node("div","","item"),detail=node("div");
 detail.append(node("strong",x.name),node("div",x.host+" · "+x.source,"small"));const btn=node("button","Pair","secondary");
 btn.onclick=async()=>{const name=prompt("Bridge name:",x.configured_as||"bridge1");
  if(name===null)return;if(!/^[a-z][a-z0-9_]*$/.test(name)){notice("Invalid Bridge name.",true);return;}
  if(!confirm("Press the physical link button on "+x.host+" before continuing."))return;
  btn.disabled=true;try{const r=await request("/manage/pair",{name,host:x.host});notice(r.message);await refresh();}
  catch(e){notice(e.message,true);}finally{btn.disabled=false;}};
 row.append(detail,btn);box.append(row);}});
async function identifyLamp(light,button){
 if(button.disabled)return;
 button.disabled=true;
 const previous=button.textContent;
 button.textContent="Flashing…";
 try{
  const result=await request("/manage/identify",{bridge:light.bridge,id:light.id});
  notice(result.message||"Light identified.");
 }catch(e){notice("Could not identify "+light.name+": "+e.message,true);}
 finally{button.disabled=false;button.textContent=previous;}
}
run("scanlights",async()=>{const box=$("lights");box.replaceChildren(node("p","Scanning lamps…"));
 lamps=await request("/manage/lights");box.replaceChildren();showSelected(configuredLights,lamps);
 const groups=new Map();for(const [i,x] of lamps.entries()){
  if(!groups.has(x.bridge))groups.set(x.bridge,[]);
  groups.get(x.bridge).push({index:i,light:x});
 }
 for(const [bridge,items] of [...groups].sort((a,b)=>alphabetical(a[0],b[0]))){
  items.sort((a,b)=>alphabetical(a.light.name,b.light.name)||alphabetical(a.light.id,b.light.id));
  const heading=node("h4",bridge+" · "+items.length+" available light"+(items.length===1?"":"s"),"light-group-heading");
  box.append(heading);
  for(const {index,light:x} of items){
   const label=node("div","","item"),checkbox=document.createElement("input");
   checkbox.type="checkbox";checkbox.className="indicator-select";checkbox.dataset.index=index;checkbox.checked=x.selected;
   const detail=node("div");detail.append(node("strong",x.name),node("div",x.capability+" · ID: "+x.id,"small"));
   const identify=node("button","Identify","secondary");identify.type="button";
   identify.setAttribute("aria-label","Identify "+x.name+" on "+x.bridge);
   const controls=node("div","","controls");
   const pick=node("label","","controls");pick.append(checkbox,node("span","Indicator","small"));
   controls.append(identify,pick);
   if(x.gradient_capable){
    const gradientBox=document.createElement("input");gradientBox.type="checkbox";
    gradientBox.className="always-gradient";
    gradientBox.dataset.index=index;
    gradientBox.checked=Boolean(x.always_gradient);
    const gradientLabel=node("label","","controls");
    gradientLabel.title="Display all collection colours on this gradient lamp even in Priority mode.";
    gradientLabel.append(gradientBox,node("span","Always multi-colour","small"));
    controls.append(gradientLabel);
   }
   identify.onclick=async(event)=>{event.preventDefault();await identifyLamp(x,identify);};
   checkbox.onchange=()=>{if(checkbox.checked)identifyLamp(x,identify);};
   label.append(detail,controls);box.append(label);
  }
 }
 if(!lamps.length)box.append(node("p","No colour-capable paired lamps found."));
});
run("savelights",async()=>{
 const checked=new Set([...$("lights").querySelectorAll(".indicator-select:checked")].map(c=>Number(c.dataset.index)));
 // Display is alphabetical, but saved selection order sets Hue colour
 // priority. Preserve the existing order, then append newly selected lamps
 // in the original API order rather than the visual sort order.
 const keys=new Set([...checked].map(i=>lamps[i].bridge+"/"+lamps[i].id));
 const gradientKeys=new Set([...$("lights").querySelectorAll(".always-gradient:checked")]
    .map(c=>{const x=lamps[Number(c.dataset.index)];return x.bridge+"/"+x.id;}));
 const selected=configuredLights.filter(x=>keys.has(x.bridge+"/"+x.id))
    .map(x=>({...x,always_gradient:gradientKeys.has(x.bridge+"/"+x.id)}));
 const preserved=new Set(selected.map(x=>x.bridge+"/"+x.id));
 for(const [i,x] of lamps.entries()){
  const key=x.bridge+"/"+x.id;
  if(checked.has(i)&&!preserved.has(key)){selected.push({bridge:x.bridge,id:x.id,always_gradient:gradientKeys.has(key)});preserved.add(key);}
 }
 const r=await request("/manage/lights",{selected});notice(r.message);configuredLights=selected;
 for(const x of lamps){x.selected=keys.has(x.bridge+"/"+x.id);x.always_gradient=gradientKeys.has(x.bridge+"/"+x.id);}
 showSelected(selected,lamps);
});
run("saveschedule",async()=>{const start=$("starttime").value,restore=$("restoretime").value;
 const result=await request("/manage/schedule",{start,restore});notice(result.message||"Schedule saved.");await refresh();});
run("savemode",async()=>{const r=await request("/manage/mode",{mode:$("mode").value});notice(r.message);});
$("addcolour").onclick=()=>{if($("colourrows").children.length>=5){notice("You can configure up to five colours.",true);return;}addColour();syncPriorityFromEditor();syncEventChoices();markDirty();};
$("refreshevents").onclick=refreshCalendarEventOptions;
$("discardcolours").onclick=()=>{if(!dirty||confirm("Discard unsaved colour and mapping changes?"))refresh();};
$("discardcoloursection").onclick=()=>$("discardcolours").click();
$("savecoloursection").onclick=()=>$("savecolours").click();
run("savecolours",async()=>{const value={};for(const row of $("colourrows").children){
 const name=row.children[2].value.trim(),hex=row.children[4].value.trim();
 if(!/^[a-z][a-z0-9_]{0,31}$/.test(name))throw Error("Invalid colour name: "+name);
 if(Object.prototype.hasOwnProperty.call(value,name))throw Error("Duplicate colour: "+name);
 if(!/^#[0-9a-f]{6}$/i.test(hex))throw Error("Invalid HEX colour for "+name);
 const inputs=row.querySelectorAll("details input");
 // HEX is authoritative when changed, even if the input's change/blur
 // event has not fired before Save. Only explicitly edited advanced
 // coordinates override HEX. Unedited existing xy is preserved exactly.
 const typedHex=hex.toUpperCase();
 let xy;
 if(row.dataset.edited==="xy"){
   xy={x:Number(inputs[0].value),y:Number(inputs[1].value)};
 }else if(typedHex!==row.dataset.originalHex || row.dataset.edited==="rgb"){
   xy=rgbToXY(typedHex);
 }else{
   xy={x:Number(row.dataset.originalX),y:Number(row.dataset.originalY)};
 }
 if(!(Number.isFinite(xy.x)&&Number.isFinite(xy.y)&&xy.x>0&&xy.y>0&&xy.x+xy.y<1))
   throw Error("Invalid CIE xy for "+name);
 value[name]=xy;
 }
 // A colour's original identifier is retained in the editor row even
 // when renamed, so event mappings and priority can follow that rename.
 const renames={};for(const row of $("colourrows").children){
  const previous=row.dataset.originalName,current=row.children[2].value.trim();
  if(previous&&previous!==current)renames[previous]=current;
 }
 syncOrderFromRows();
 if(Object.keys(value).length>5)throw Error("Maximum five colours.");
 const events={};
 for(const [title,previousColour] of Object.entries(eventAssignments)){
  const colour=eventColourName(previousColour);
  if(!title.trim()||!Object.prototype.hasOwnProperty.call(value,colour))
   throw Error("Event "+title+" needs a configured colour.");
  events[title]=colour;
 }
 if(priorityOrder.length!==Object.keys(value).length)throw Error("Colour priority contains incomplete names.");
 const r=await request("/manage/colours",{value:{colours:value,renames,priority:[...priorityOrder],events}});
 notice(r.message);await refresh();});
run("savepriority",async()=>{const r=await request("/manage/priority",{value:[...priorityOrder]});notice(r.message);await refresh();});
function showSourceDates(source,response,preview){
 const box=$(source==="council"?"councilresults":"icalresults");
 box.replaceChildren(node("p",preview
  ?response.count+" upcoming collection date(s) found (first 12 shown)."
  :"Connection successful. Calendar accessible."));
 if(preview)for(const item of response.dates){
  box.append(node("div",item.date+" · "+item.collections.join(", ")));
 }
}
async function checkSource(source,preview){
 const response=await request("/manage/calendar/check",{source,preview});
 showSourceDates(source,response,preview);
}
run("savesource",async()=>{
 const source=$("activesource").value;
 if(!confirm("Use "+(source==="council"?"North Yorkshire Council":"iCalendar")+" for reminders, Status and Alexa?"))return;
 await request("/manage/calendar-source",{source});
 notice("Active calendar changed.");await refresh();
});
run("saveinterval",async()=>{
 const days=Number($("calendarinterval").value);
 if(!Number.isInteger(days)||days<1||days>90)throw Error("Choose 1–90 whole days.");
 await request("/manage/calendar-refresh",{days});
 notice("Calendar refresh interval updated.");await refresh();
});
run("refreshactive",async()=>{
 const result=await request("/manage/calendar/refresh",{});
 notice(result.refreshed?"Active calendar refreshed successfully.":"Calendar is up to date.");
 await refresh();
});
run("savecouncil",async()=>{
 const uprn=$("counciluprn").value.trim();
 const active=currentActiveSource==="council";
 const result=await request("/manage/north-yorkshire",
 {uprn,enabled:active,refresh_days:councilLegacyRefreshDays});
 $("counciluprn").value="";notice(result.message||"Council settings saved.");await refresh();
 await refreshCalendarEventOptions();
});
run("counciltest",async()=>checkSource("council",false));
run("councilpreview",async()=>checkSource("council",true));
run("savecalendar",async()=>{
 const url=$("calendarurl").value.trim();
 if(!url||!confirm("Replace your saved private iCalendar feed URL?"))return;
 const r=await request("/manage/calendar",{url});
 $("calendarurl").value="";notice(r.message||"iCalendar URL saved.");
 await refresh();await refreshCalendarEventOptions();
});
run("icaltest",async()=>checkSource("ical",false));
run("icalpreview",async()=>checkSource("ical",true));
refresh();
</script></body></html>'''
