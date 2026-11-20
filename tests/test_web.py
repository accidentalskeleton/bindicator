"""LAN management UI safety regressions. No Hue devices or network needed."""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from bindicator.app import BindicatorError
from bindicator.web import Management, private_host, update_mode, update_configuration, save_calendar_url, calendar_url_present
from bindicator.web_ui import HTML


@pytest.mark.parametrize("ip", ["0.0.0.0", "127.0.0.1", "169.254.1.2", "8.8.8.8", "::1", "not-an-ip"])
def test_rejects_public_loopback_or_wildcard(ip):
    with pytest.raises(BindicatorError):
        private_host(ip)


def test_accepts_private_lan_ip():
    assert private_host("192.168.1.20") == "192.168.1.20"


def test_webpage_has_discovery_configuration_and_preview_buttons():
    for label in ("Discover Bridges", "Save selected lights", "Save mode", "quicktests", "/manage/preview", "tab-status", "tab-testing", "tab-lighting", "tab-colours", "tab-calendars", "tab-mapping", "Pause", "Resume", "Toggle", "calendarurl", "savecolours", "refreshevents"):
        assert label in HTML
    assert "BINDICATOR_ICAL_URL" not in HTML
    assert HTML.count('class="admin-section"') == 8
    assert '<summary>Indicator colours</summary>' in HTML
    assert '<summary>Calendar event mappings</summary>' in HTML
    assert 'id="starttime"' in HTML and 'id="restoretime"' in HTML
    assert 'id="saveschedule"' in HTML
    assert 'id="selectedlights"' in HTML
    assert 'class="light-list-divider"' in HTML
    assert 'Available lights by Hue Bridge' in HTML
    assert 'const groups=new Map()' in HTML
    assert 'checkbox.dataset.index=index' in HTML
    assert 'items.length' in HTML
    assert 'items.sort((a,b)=>alphabetical(a.light.name,b.light.name)' in HTML
    assert '.sort((a,b)=>alphabetical(a.name,b.name)' in HTML
    assert 'configuredLights.filter(x=>keys.has(x.bridge+"/"+x.id))' in HTML
    assert 'checked.has(i)&&!preserved.has(key)' in HTML
    assert 'rgbToXY' in HTML and 'xyToHex' in HTML
    assert 'type="color"' not in HTML  # The picker is constructed dynamically.
    assert 'inp(xyToHex(xy),"color")' in HTML
    assert 'row.dataset.edited==="xy"' in HTML
    assert 'showSelected(configuredLights,lamps)' in HTML


def test_update_mode_preserves_calendar_and_comments(tmp_path):
    file = tmp_path / "config.yaml"
    file.write_text("# keep comment\ncalendar:\n  events:\n    'Garden Waste': orange\nhue:\n  bridges: {}\n  lights: []\n  mode: spread\n")
    update_mode(file, "priority")
    new = file.read_text()
    assert "mode: priority" in new
    assert "Garden Waste" in new
    assert "# keep comment" in new
    with pytest.raises(ValueError):
        update_mode(file, "bogus")


def test_preview_validates_colour_duration_and_uses_fixed_cli(monkeypatch, tmp_path):
    manager = Management(tmp_path / "config.yaml", tmp_path / "secrets.env", tmp_path / "state")
    monkeypatch.setattr(manager, "_config", lambda: {"colors": {"green": {}, "orange": {}}})
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr("bindicator.web.subprocess.run", fake_run)
    for payload in ({"colour":"bad","seconds":5}, {"colour":"green","seconds":0},
                    {"colour":"green","seconds":True}, {"colour":"green","seconds":31},
                    {"colour":"green","seconds":5,"extra":1}):
        with pytest.raises(ValueError):
            manager.preview(payload)
    assert not calls
    response = manager.preview({"colour":"orange","seconds":10})
    assert response["ok"] is True
    assert len(calls) == 1
    cmd, options = calls[0]
    assert cmd[-4:] == ["--test", "orange", "--seconds", "10"]
    assert options["timeout"] == 40
    assert options["shell"] is not True if "shell" in options else True


def test_preview_failure_is_safe(monkeypatch, tmp_path):
    manager = Management(tmp_path / "config.yaml", tmp_path / "secrets.env", tmp_path / "state")
    monkeypatch.setattr(manager, "_config", lambda: {"colors": {"green": {}}})
    monkeypatch.setattr("bindicator.web.subprocess.run", lambda *a,**kw: SimpleNamespace(returncode=1,stderr="refused",stdout=""))
    with pytest.raises(BindicatorError, match="refused"):
        manager.preview({"colour":"green","seconds":5})

def test_update_colours_and_events_preserves_comments(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("""# important
calendar:
  events:
    Garden Waste: green
hue:
  bridges: {}
  lights: []
  mode: spread
colors:
  green: {x: 0.21, y: 0.65}
priority: [green]
""")
    update_configuration(p, section="colours", value={"green":{"x":0.25,"y":0.6},"orange":{"x":0.57,"y":0.39}})
    update_configuration(p, section="events", value={"Garden Waste":"green","Household waste":"orange"})
    update_configuration(p, section="priority", value=["orange","green"])
    assert "# important" in p.read_text()
    assert "Household waste" in p.read_text()
    with pytest.raises(ValueError):
        update_configuration(p, section="colours", value={"orange":{"x":0.9,"y":0.9}})


def test_calendar_url_not_leaked(tmp_path):
    p = tmp_path / "secrets.env"
    p.write_text('BINDICATOR_HUE_KEY_OFFICE="123456789012"\n')
    assert not calendar_url_present(p)
    save_calendar_url(p, "https://calendar.zoho.com/ical/private/test")
    assert calendar_url_present(p)
    assert "BINDICATOR_HUE_KEY_OFFICE" in p.read_text()
    assert "calendar.zoho.com" in p.read_text()
    with pytest.raises(ValueError):
        save_calendar_url(p, "http://evil.example/ical")


def test_embedded_javascript_syntax(tmp_path):
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("Node.js not installed")
    script = HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    path = tmp_path / "management.js"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_rgb_hex_primary_colours_convert_to_valid_xy(tmp_path):
    """Exercise the actual browser RGB conversion code, not a Python copy."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("Node.js not installed")
    script = HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("function rgbToXY(hex){")
    end = script.index("function xyToHex(", start)
    conversion = script[start:end]
    assertions = """
for (const hex of ["#0000FF", "#FF0000", "#00FF00", "#FFFFFF", "#FF9900"]) {
  const xy = rgbToXY(hex);
  if (!(Number.isFinite(xy.x) && Number.isFinite(xy.y) &&
        xy.x > 0 && xy.y > 0 && xy.x + xy.y < 1))
    throw Error(hex + " converted to invalid xy: " + JSON.stringify(xy));
}
const blue = rgbToXY("#0000FF");
if (Math.abs(blue.x - 0.150) > 0.002 || Math.abs(blue.y - 0.060) > 0.002)
  throw Error("Unexpected pure-blue conversion: " + JSON.stringify(blue));
"""
    file = tmp_path / "rgb-test.js"
    file.write_text(conversion + assertions, encoding="utf-8")
    result = subprocess.run(["node", str(file)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_colour_save_treats_edited_hex_as_authoritative():
    assert 'typedHex!==row.dataset.originalHex' in HTML
    assert 'xy=rgbToXY(typedHex)' in HTML
    assert 'r.dataset.originalHex=picker.value.toUpperCase()' in HTML


def test_schedule_web_validation_and_atomic_save(tmp_path):
    from bindicator.app import load_config
    from bindicator.web import Management
    p = tmp_path / "config.yaml"
    p.write_text("""# preserve me
calendar:
  events:
    Garden Waste: green
hue:
  bridges: {}
  lights: []
  mode: spread
colors:
  green: {x: 0.21, y: 0.65}
priority: [green]
""")
    state = tmp_path / "state"
    state.mkdir()
    secrets = tmp_path / "secrets.env"
    secrets.write_text("")
    manager = Management(p, secrets, state)
    assert manager.change("schedule", {"start": "17:30", "restore": "08:15"})["ok"]
    assert load_config(p)["schedule"] == {"start": "17:30", "restore": "08:15"}
    assert "# preserve me" in p.read_text()
    for invalid in ({"start": "11:59", "restore": "09:00"},
                    {"start": "17:00", "restore": "12:00"},
                    {"start": "17:00", "restore": "08:30", "other": 1},
                    {"start": "foo", "restore": "08:30"}):
        with pytest.raises((ValueError, BindicatorError)):
            manager.change("schedule", invalid)
    assert load_config(p)["schedule"] == {"start": "17:30", "restore": "08:15"}


def test_identify_ui_action_and_checkbox_flash():
    assert '/manage/identify' in HTML
    assert 'checkbox.onchange=()=>{if(checkbox.checked)identifyLamp(x,identify);};' in HTML
    assert 'Identify "+x.name+" on "+x.bridge' in HTML
    assert 'const result=await request("/manage/identify",{bridge:light.bridge,id:light.id});' in HTML


def test_identify_refuses_unpaired_or_unknown_lamps(tmp_path, monkeypatch):
    manager = Management(tmp_path / "config.yaml", tmp_path / "secrets.env", tmp_path / "state")
    monkeypatch.setattr(manager, "_config", lambda: {
        "hue": {"bridges": {"downstairs": {"host": "192.168.1.2"}}, "lights": []}
    })
    for payload in ({}, {"bridge": "x", "id": "a", "extra": 1},
                    {"bridge": "unknown", "id": "a"}, {"bridge": 2, "id": "a"}):
        with pytest.raises(ValueError):
            manager.identify(payload)
    monkeypatch.setattr(manager.api, "status", lambda: {
        "paused": True, "indicator_count": 0, "manual_until": None
    })
    with pytest.raises(BindicatorError, match="paused"):
        manager.identify({"bridge": "downstairs", "id": "a"})


def test_upcoming_list_and_selected_date_preview(monkeypatch, tmp_path):
    manager = Management(tmp_path / "config.yaml", tmp_path / "secrets.env", tmp_path / "state")
    feed = b"calendar feed"
    fake = SimpleNamespace(
        config={"colors": {"green": {"x": 0.2, "y": 0.6}}, "priority": ["green"]},
        state={"lights": {}, "manual_until": None},
        hue=object(),
        calendar_data=lambda: feed,
    )
    monkeypatch.setattr(manager.api, "_app", lambda: fake)
    monkeypatch.setattr("bindicator.controls.is_paused", lambda _: False)
    captured = []
    def fake_upcoming(config, data, now):
        assert data is feed
        return [{"date": "2099-01-05", "weekday": "Monday",
                 "collections": ["Garden Waste"], "colours": ["green"]}]
    def fake_preview(pool, config, colours, seconds):
        captured.append((pool, colours, seconds))
    monkeypatch.setattr("bindicator.bin_preview.upcoming_collections", fake_upcoming)
    monkeypatch.setattr("bindicator.bin_preview.preview_lights", fake_preview)
    assert len(manager.upcoming()) == 1
    response = manager.test_collection({"date": "2099-01-05", "seconds": 10})
    assert response["ok"]
    assert captured == [(fake.hue, ["green"], 10)]
    for body in (
        {}, {"date": "2099-01-05"}, {"date": "2099-01-05", "seconds": True},
        {"date": "2099-01-05", "seconds": 31},
        {"date": "2099-01-06", "seconds": 10},
        {"date": "invalid", "seconds": 10},
    ):
        with pytest.raises(ValueError):
            manager.test_collection(body)
    assert len(captured) == 1


def test_upcoming_preview_refuses_paused_and_active_reminders(monkeypatch, tmp_path):
    manager = Management(tmp_path / "config.yaml", tmp_path / "secrets.env", tmp_path / "state")
    fake = SimpleNamespace(config={}, state={"lights": {}, "manual_until": None}, hue=object())
    monkeypatch.setattr(manager.api, "_app", lambda: fake)
    monkeypatch.setattr("bindicator.controls.is_paused", lambda _: True)
    body = {"date": "2099-01-05", "seconds": 10}
    with pytest.raises(BindicatorError, match="paused"):
        manager.test_collection(body)
    monkeypatch.setattr("bindicator.controls.is_paused", lambda _: False)
    fake.state["lights"] = {"bridge/light": {}}
    with pytest.raises(BindicatorError, match="active"):
        manager.test_collection(body)


def test_five_upcoming_alerts_ui():
    assert 'id="upcoming"' in HTML
    assert '"/manage/upcoming"' in HTML
    assert '"/manage/collections/test"' in HTML
    assert 'date:item.date,seconds:10' in HTML
    assert '"Test 10s"' in HTML
    assert 'run("upcomingrefresh",refresh)' in HTML


def test_remove_bridge_deletes_only_its_settings_lights_and_key(tmp_path):
    from bindicator.bridge_setup import remove_bridge_config_and_key
    from bindicator.app import load_config
    cfg = tmp_path / "config.yaml"
    sec = tmp_path / "secrets.env"
    cfg.write_text("""# preserve all other settings
calendar:
  events: {Garden Waste: green}
hue:
  bridges:
    kitchen: {host: 192.168.1.2}
    office: {host: 192.168.1.3}
  lights:
    - {bridge: kitchen, id: light1}
    - {bridge: office, id: light2}
    - {bridge: kitchen, id: light3}
  mode: spread
colors:
  green: {x: 0.21, y: 0.65}
priority: [green]
""")
    sec.write_text('BINDICATOR_ICAL_URL="https://calendar.zoho.com/private"\n'
                   'BINDICATOR_HUE_KEY_KITCHEN="secret1"\n'
                   'export BINDICATOR_HUE_KEY_OFFICE="secret2"\n'
                   'BINDICATOR_HUE_KEY_KITCHEN_EXTRA="keep"\n')
    assert remove_bridge_config_and_key(cfg, sec, "kitchen") == 2
    result = load_config(cfg)
    assert list(result["hue"]["bridges"]) == ["office"]
    assert result["hue"]["lights"] == [{"bridge": "office", "id": "light2"}]
    assert result["hue"]["mode"] == "spread"
    assert "# preserve all other settings" in cfg.read_text()
    contents = sec.read_text()
    assert "BINDICATOR_HUE_KEY_KITCHEN=" not in contents
    assert "BINDICATOR_HUE_KEY_OFFICE=" in contents
    assert "BINDICATOR_HUE_KEY_KITCHEN_EXTRA=" in contents
    assert "BINDICATOR_ICAL_URL=" in contents
    assert remove_bridge_config_and_key(cfg, sec, "office") == 1
    assert load_config(cfg)["hue"]["bridges"] == {}
    assert load_config(cfg)["hue"]["lights"] == []
    with pytest.raises(BindicatorError, match="not configured"):
        remove_bridge_config_and_key(cfg, sec, "office")


def test_remove_bridge_validation_does_not_modify_files(tmp_path):
    from bindicator.bridge_setup import remove_bridge_config_and_key
    cfg = tmp_path / "config.yaml"
    sec = tmp_path / "secrets.env"
    cfg.write_text("hue:\n  bridges:\n    kitchen: {host: 192.168.1.2}\n  lights: []\n")
    sec.write_text('BINDICATOR_HUE_KEY_KITCHEN="secret"\n')
    before = (cfg.read_text(), sec.read_text())
    for invalid in ("", "../bad", "unlisted"):
        with pytest.raises(BindicatorError):
            remove_bridge_config_and_key(cfg, sec, invalid)
    assert (cfg.read_text(), sec.read_text()) == before


def test_delete_bridge_route_refuses_active_state(tmp_path, monkeypatch):
    manager = Management(tmp_path / "config.yaml", tmp_path / "secrets.env", tmp_path / "state")
    manager.state.mkdir()
    monkeypatch.setattr(manager, "_config", lambda: {
        "hue": {"bridges": {"kitchen": {"host": "192.168.1.2"}}, "lights": []}
    })
    monkeypatch.setattr(manager.api, "status", lambda: {
        "indicator_count": 1, "manual_until": None
    })
    with pytest.raises(BindicatorError, match="active reminder"):
        manager.change("delete_bridge", {"name": "kitchen"})
    for value in ({}, {"name": "bad/bridge"}, {"name": "missing"}):
        with pytest.raises(ValueError):
            manager.change("delete_bridge", value)


def test_delete_bridge_ui_confirmation_and_refresh():
    assert '"/manage/bridges/delete"' in HTML
    assert 'renderConfiguredBridges(v.bridges)' in HTML
    assert 'id="discoveredbridges"' in HTML
    assert 'const box=$("discoveredbridges")' in HTML
    assert 'Delete Hue Bridge ' in HTML
    assert 'configuredLights=configuredLights.filter(x=>x.bridge!==bridge.name)' in HTML


def test_priority_colour_order_uses_visual_buttons_instead_of_text_entry():
    assert 'id="priorityrows"' in HTML
    assert 'id="priority" type="text"' not in HTML
    assert 'function movePriority(index,direction)' in HTML
    assert 'up.onclick=()=>movePriority(index,-1)' in HTML
    assert 'down.onclick=()=>movePriority(index,1)' in HTML
    assert 'priorityOrder=[...v.priority]' in HTML
    assert 'request("/manage/priority",{value:[...priorityOrder]})' in HTML
    assert 'priority-swatch' in HTML


def _colour_sync_fixture(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("""# keep this comment
calendar:
  events:
    BinDay - Recycling: blue
    BinDay - General: orange
hue:
  bridges: {}
  lights: []
  mode: priority
colors:
  blue: {x: 0.17, y: 0.08}
  orange: {x: 0.57, y: 0.39}
  green: {x: 0.21, y: 0.65}
priority: [orange, blue, green]
""")
    return path


def test_colour_sync_add_change_and_delete_unused(tmp_path):
    from bindicator.app import load_config
    path = _colour_sync_fixture(tmp_path)
    new_palette = {
        "orange": {"x": .55, "y": .37},
        "blue": {"x": .17, "y": .08},
        "purple": {"x": .3, "y": .2},
    }
    update_configuration(path, section="colours", value=new_palette)
    config = load_config(path)
    assert list(config["colors"]) == ["orange", "blue", "purple"]
    assert config["priority"] == ["orange", "blue", "purple"]
    assert config["colors"]["orange"]["x"] == .55
    assert config["calendar"]["events"]["BinDay - Recycling"] == "blue"
    assert "# keep this comment" in path.read_text()


def test_colour_sync_rename_preserves_position_and_calendar_events(tmp_path):
    from bindicator.app import load_config
    path = _colour_sync_fixture(tmp_path)
    palette = {
        "recycling": {"x": .17, "y": .08},
        "orange": {"x": .57, "y": .39},
        "green": {"x": .21, "y": .65},
    }
    update_configuration(path, section="colours", value={
        "colours": palette, "renames": {"blue": "recycling"},
        "priority": ["orange", "recycling", "green"],
    })
    result = load_config(path)
    assert result["priority"] == ["orange", "recycling", "green"]
    assert result["calendar"]["events"]["BinDay - Recycling"] == "recycling"
    assert "blue" not in result["colors"]


def test_colour_sync_rejects_used_deletion_without_partial_write(tmp_path):
    path = _colour_sync_fixture(tmp_path)
    before = path.read_text()
    with pytest.raises(ValueError, match="Reassign or remove"):
        update_configuration(path, section="colours", value={
            "orange": {"x": .57, "y": .39},
            "green": {"x": .21, "y": .65},
        })
    assert path.read_text() == before


def test_colour_sync_rejects_rename_collision_and_bad_priority(tmp_path):
    path = _colour_sync_fixture(tmp_path)
    old = path.read_text()
    palette = {
        "blue": {"x": .17, "y": .08},
        "orange": {"x": .57, "y": .39},
        "green": {"x": .21, "y": .65},
    }
    for renames, priority in (
        ({"blue": "orange"}, ["orange", "blue", "green"]),
        ({}, ["orange", "orange", "blue"]),
        ({"missing": "green"}, ["orange", "blue", "green"]),
    ):
        with pytest.raises(ValueError):
            update_configuration(path, section="colours", value={
                "colours": palette, "renames": renames, "priority": priority
            })
        assert path.read_text() == old


def test_colour_editor_syncs_priority_dynamically():
    assert 'function syncPriorityFromEditor()' in HTML
    assert 'nameInput.oninput=()=>{syncPriorityFromEditor();syncEventChoices();markDirty();}' in HTML
    assert 'syncPriorityFromEditor();' in HTML
    assert 'row.dataset.originalName' in HTML
    assert 'renames[previous]=current' in HTML
    assert 'colours:value,renames,priority:[...priorityOrder]' in HTML


def test_five_colour_limit_and_atomic_editor_update(tmp_path):
    from bindicator.app import load_config, BindicatorError
    p = _colour_sync_fixture(tmp_path)
    palette = {name: {"x": .3, "y": .3} for name in ("one", "two", "three", "four", "five")}
    update_configuration(p, section="colours", value={
        "colours": palette,
        "renames": {},
        "priority": list(palette),
        "events": {"Recycling": "one", "Household waste": "two"},
    })
    config = load_config(p)
    assert len(config["colors"]) == 5
    assert config["calendar"]["events"]["Recycling"] == "one"
    assert config["priority"] == list(palette)
    before = p.read_text()
    with pytest.raises(ValueError, match="five"):
        update_configuration(p, section="colours", value={
            **palette, "six": {"x": .2, "y": .6}
        })
    assert p.read_text() == before
    p.write_text(before.replace("  five:", "  five:\n  six:"))
    with pytest.raises(BindicatorError):
        load_config(p)


def test_cycle_mode_configuration_and_integrated_editor(tmp_path):
    from bindicator.app import load_config
    p = _colour_sync_fixture(tmp_path)
    update_mode(p, "cycle")
    assert load_config(p)["hue"]["mode"] == "cycle"
    assert 'value="cycle"' in HTML
    assert 'id="colourcount"' in HTML
    assert 'id="discardcolours"' in HTML
    assert 'syncEventChoices()' in HTML
    assert 'priority:[...priorityOrder],events' in HTML


def test_bindicator_brand_assets_bundled_and_declared():
    from importlib.resources import files
    # The packaged service must be able to serve these without external assets.
    static = files("bindicator").joinpath("static")
    favicon = static.joinpath("favicon-32.png").read_bytes()
    soft_banner = static.joinpath("bindicator-soft-banner.webp").read_bytes()
    assert soft_banner.startswith(b"RIFF") and soft_banner[8:12] == b"WEBP"
    assert len(soft_banner) > 30000
    assert favicon.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(favicon) > 500
    assert 'src="/static/bindicator-soft-banner.webp"' in HTML
    assert 'href="/favicon-32.png"' in HTML
    assert 'alt="Bindicator"' in HTML


def test_brand_assets_served_by_existing_management_server():
    from bindicator import web
    import http.client
    from http.server import ThreadingHTTPServer
    from threading import Thread

    handler = web.make_handler(object(), "127.0.0.1", 0)
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        port = server.server_address[1]
        # Handler uses the explicitly configured Host, not its ephemeral bind port.
        handler = web.make_handler(object(), "127.0.0.1", port)
        server.RequestHandlerClass = handler
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
            page = conn.getresponse()
            assert page.status == 200
            policy = page.getheader("Content-Security-Policy")
            assert "default-src 'none'" in policy
            assert "img-src 'self'" in policy
            assert "img-src *" not in policy
            assert b'src="/static/bindicator-soft-banner.webp"' in page.read()
            conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/static/bindicator-soft-banner.webp", headers={"Host": f"127.0.0.1:{port}"})
            response = conn.getresponse()
            assert response.status == 200
            assert response.getheader("Content-Type") == "image/webp"
            assert response.read().startswith(b"RIFF")
            conn.close()
            for url in ("/favicon-32.png", "/favicon.ico"):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", url, headers={"Host": f"127.0.0.1:{port}"})
                response = conn.getresponse()
                assert response.status == 200
                assert response.getheader("Content-Type") == "image/png"
                assert response.read().startswith(b"\x89PNG")
                conn.close()
            for retired in ("/static/bindicator-logo.png", "/static/bindicator-wide-logo.png"):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", retired, headers={"Host": f"127.0.0.1:{port}"})
                assert conn.getresponse().status == 404
                conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/static/../../etc/passwd", headers={"Host": f"127.0.0.1:{port}"})
            assert conn.getresponse().status != 200
            conn.close()
        finally:
            server.shutdown()
            worker.join(timeout=5)


def test_wide_branding_is_responsive_and_blends_with_page():
    assert 'class="brand-banner"' in HTML
    assert 'class="brand-meta"' in HTML
    assert "mix-blend-mode:lighten" in HTML
    assert "filter:saturate(.78) brightness(.9)" in HTML
    assert "header .brand-banner::after" in HTML
    assert "mask-image:linear-gradient" in HTML
    assert "width:100%;height:auto" in HTML


def test_main_tab_colour_and_collection_sections_are_collapsible():
    from html.parser import HTMLParser

    class DetailsParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.matches = {}
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "details":
                self.stack.append({"id": attrs.get("id"), "open": "open" in attrs, "summary": False, "content": False})
            elif self.stack and tag == "summary":
                self.stack[-1]["summary"] = True
            elif self.stack and "detail-content" in attrs.get("class", "").split():
                self.stack[-1]["content"] = True
        def handle_endtag(self, tag):
            if tag == "details" and self.stack:
                current = self.stack.pop()
                if current["id"]:
                    self.matches[current["id"]] = current

    parser = DetailsParser()
    parser.feed(HTML)
    for section_id in ("test-indicator-section", "next-collection-section"):
        section = parser.matches[section_id]
        assert section["open"] is True  # Expanded on first visit.
        assert section["summary"] is True
        assert section["content"] is True

    # Controls and refreshes stay inside the collapsible content.
    colours = HTML.split('id="test-indicator-section"', 1)[1].split("</details>", 1)[0]
    alerts = HTML.split('id="next-collection-section"', 1)[1].split("</details>", 1)[0]
    for control in ('id="testseconds"', 'id="quicktests"'):
        assert control in colours
    for control in ('id="upcoming"', 'id="upcomingrefresh"', 'id="nextpersistent"'):
        assert control in alerts


def test_status_and_testing_tabs_keep_controls_separate():
    assert 'id="tab-status"' in HTML
    assert 'id="tab-testing"' in HTML
    assert 'id="tab-calendars"' in HTML
    assert 'id="tab-lighting"' in HTML
    assert 'id="tab-colours"' in HTML
    assert 'id="tab-mapping"' in HTML
    assert 'id="tab-admin"' not in HTML
    assert 'id="tab-test"' not in HTML
    assert 'id="panel-test"' not in HTML
    status = HTML.split('id="panel-status"', 1)[1].split('id="panel-testing"', 1)[0]
    testing = HTML.split('id="panel-testing"', 1)[1].split('id="panel-lighting"', 1)[0]
    for control in ('id="next"', 'id="status"', 'id="pause"', 'id="resume"',
                    'id="toggle"', 'id="next-collection-section"', 'id="upcoming"'):
        assert control in status
    for control in ('id="test-indicator-section"', 'id="testseconds"',
                    'id="quicktests"'):
        assert control in testing
        assert control not in status
    assert 'for(const n of ["status","testing","lighting","colours","calendars","mapping","help","coffee"])' in HTML
    assert 'openTab("status")' in HTML
    assert 'openTab("testing")' in HTML


def test_hostname_host_allowlist_and_matching_post_origin():
    import http.client
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from bindicator.web import make_handler

    class StubManager:
        def change(self, action, payload):
            return {"ok": True, "action": action}

    handler = make_handler(StubManager(), "127.0.0.1", 0, allowed_hostname="mrlazy")
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        port = server.server_address[1]
        server.RequestHandlerClass = make_handler(
            StubManager(), "127.0.0.1", port, allowed_hostname="mrlazy"
        )
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def request(host, method="GET", origin=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            headers = {"Host": host}
            if method == "POST":
                headers.update({"Content-Type": "application/json",
                                "X-Bindicator-Request": "management"})
                if origin is not None:
                    headers["Origin"] = origin
            conn.request(method, "/manage/mode" if method == "POST" else "/",
                         body=b'{"value":"priority"}' if method == "POST" else None,
                         headers=headers)
            response = conn.getresponse()
            result = response.status
            response.read()
            conn.close()
            return result
        try:
            assert request(f"127.0.0.1:{port}") == 200
            assert request(f"mrlazy:{port}") == 200
            assert request(f"MRLAZY:{port}") == 200
            assert request(f"malicious.example:{port}") == 400
            assert request(f"mrlazy:{port}", "POST", f"https://mrlazy:{port}") == 200
            assert request(f"mrlazy:{port}", "POST", f"https://malicious.example:{port}") == 403
            assert request(f"127.0.0.1:{port}", "POST", f"https://mrlazy:{port}") == 403
            assert request(f"malicious.example:{port}", "POST", f"https://malicious.example:{port}") == 400
        finally:
            server.shutdown()
            worker.join(timeout=5)


@pytest.mark.parametrize("hostname", ["", ".bad", "bad.local", "localhost:80",
                                       "a" * 65, "x_unsafe", "-bad"])
def test_rejects_invalid_explicit_hostname(hostname):
    from bindicator.web import make_handler
    if not hostname:
        assert make_handler(object(), "192.168.1.69", 18051, allowed_hostname=hostname)
        return
    with pytest.raises(BindicatorError):
        make_handler(object(), "192.168.1.69", 18051, allowed_hostname=hostname)


def test_colour_test_buttons_are_generated_from_saved_palette():
    assert 'id="testcolour"' not in HTML
    assert 'id="preview"' not in HTML
    assert "Test selected colour" not in HTML
    assert 'function renderTestColours(colours,palette)' in HTML
    assert 'for(const colour of colours)' in HTML
    assert 'btn.onclick=()=>previewColour(colour,btn)' in HTML
    assert 'renderTestColours(v.colours,v.colour_xy)' in HTML
    assert 'if(name==="testing")refreshTestColours()' in HTML
    assert 'renderTestColours(overview.colours,overview.colour_xy)' in HTML
    assert 'notice(r.message);await refresh();' in HTML


def test_all_admin_accordions_start_closed():
    import re
    panels = {}
    for name, next_name in (
        ("lighting", "colours"), ("colours", "calendars"),
        ("calendars", "mapping"), ("mapping", None),
    ):
        contents = HTML.split('id="panel-'+name+'"', 1)[1]
        panels[name] = contents.split('id="panel-'+next_name+'"', 1)[0] if next_name else contents.split('<footer>', 1)[0]
    counts = {"lighting": 4, "colours": 1, "calendars": 2, "mapping": 1}
    for name, expected in counts.items():
        sections = re.findall(r'<details class="admin-section"[^>]*>', panels[name])
        assert len(sections) == expected
        assert all(' open' not in section for section in sections)
    assert '<summary>Indicator colours</summary>' in panels["colours"]
    assert '<summary>Calendar event mappings</summary>' in panels["mapping"]


def test_dynamic_colour_buttons_show_saved_hue_colour_dots():
    assert 'class="colour-test-dot"' not in HTML  # Constructed dynamically.
    assert 'const dot=node("span","","colour-test-dot")' in HTML
    assert 'dot.setAttribute("aria-hidden","true")' in HTML
    assert 'dot.style.backgroundColor=xyToHex(palette[colour])' in HTML
    assert 'btn.append(dot,node("span","Test "+colour))' in HTML
    assert 'button.colour-test{display:inline-flex' in HTML
    assert '.colour-test-dot{display:inline-block' in HTML
    assert 'renderTestColours(v.colours,v.colour_xy)' in HTML
    assert 'renderTestColours(overview.colours,overview.colour_xy)' in HTML


def test_calendar_settings_have_shared_source_controls_and_consistent_actions():
    assert '<h2>Active calendar source</h2>' in HTML
    assert 'id="activesource"' in HTML
    assert 'id="calendarinterval"' in HTML
    assert 'id="saveinterval"' in HTML
    assert 'id="refreshactive"' in HTML
    assert 'id="savesource"' in HTML
    assert '<summary>North Yorkshire Council</summary>' in HTML
    assert '<summary>iCalendar (iCal)</summary>' in HTML
    for element in ('counciltest', 'councilpreview', 'icaltest', 'icalpreview',
                    'counciluprn', 'savecouncil', 'calendarurl', 'savecalendar'):
        assert 'id="'+element+'"' in HTML
    assert 'request("/manage/calendar/check",{source,preview})' in HTML
    assert 'request("/manage/calendar/refresh",{})' in HTML
    assert 'request("/manage/calendar-source",{source})' in HTML
    assert 'request("/manage/calendar-refresh",{days})' in HTML
    assert 'currentActiveSource==="council"' in HTML


def test_council_source_selection_is_opt_in_and_non_disclosing(monkeypatch, tmp_path):
    from bindicator.web import Management
    from bindicator.app import load_config
    from bindicator import north_yorkshire
    config_path = tmp_path / "config.yaml"
    secrets = tmp_path / "secrets.env"
    secrets.write_text("")
    config_path.write_text("""calendar:
  events:
    'BinDay - Recycling': blue
hue:
  bridges: {}
  lights: []
  mode: priority
colors:
  blue: {x: 0.17, y: 0.08}
priority: [blue]
""")
    mgr = Management(config_path, secrets, tmp_path)
    assert load_config(config_path)["north_yorkshire"] == {"enabled": False, "uprn": "", "refresh_days": 7}
    records = [{"date": "2030-01-01", "title": "BinDay - Recycling", "type": "Recycling"}]
    monkeypatch.setattr(north_yorkshire, "fetch_collections", lambda uprn: records)
    checked = mgr.check_north_yorkshire({"uprn": "12345678901"})
    assert checked["count"] == 1 and checked["entries"][0]["mapped"]
    assert "north_yorkshire" not in config_path.read_text()
    mgr.change("north_yorkshire", {"uprn": "12345678901", "enabled": False, "refresh_days": 7})
    assert load_config(config_path)["north_yorkshire"]["enabled"] is False
    assert "12345678901" in config_path.read_text()
    mgr.change("north_yorkshire", {"uprn": "", "enabled": True, "refresh_days": 7})
    assert load_config(config_path)["north_yorkshire"]["enabled"] is True
    assert mgr.overview()["north_yorkshire"]["configured"] is True
    assert mgr.overview()["north_yorkshire"]["enabled"] is True
    assert mgr.overview()["north_yorkshire"]["refresh_days"] == 7
    assert "12345678901" not in str(mgr.overview()["north_yorkshire"])


def test_council_cannot_activate_without_matching_colour_mapping(monkeypatch, tmp_path):
    from bindicator.web import Management
    from bindicator import north_yorkshire
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""calendar:
  events:
    'BinDay - Recycling': blue
hue:
  bridges: {}
  lights: []
  mode: priority
colors:
  blue: {x: 0.17, y: 0.08}
priority: [blue]
""")
    monkeypatch.setattr(
        north_yorkshire, "fetch_collections",
        lambda uprn: [{"date": "2030-01-01", "title": "BinDay - Garden Waste", "type": "Garden Waste"}],
    )
    mgr = Management(config_path, tmp_path / "secret.env", tmp_path)
    with pytest.raises(ValueError, match="matching calendar-event colour mappings"):
        mgr.change("north_yorkshire", {"uprn": "12345678901", "enabled": True, "refresh_days": 7})
    assert "north_yorkshire" not in config_path.read_text()


def test_indicator_colours_and_event_mappings_are_separate_and_atomically_saved():
    colours = HTML.split('id="panel-colours"', 1)[1].split('id="panel-calendars"', 1)[0]
    mapping = HTML.split('id="panel-mapping"', 1)[1].split('id="panel-help"', 1)[0]
    palette = colours.split('<summary>Indicator colours</summary>', 1)[1].split('</details>', 1)[0]
    mappings = mapping.split('<summary>Calendar event mappings</summary>', 1)[1].split('</details>', 1)[0]
    assert 'id="colourrows"' in palette and 'id="eventrows"' not in palette
    assert 'id="eventrows"' in mappings and 'id="colourrows"' not in mappings
    assert 'id="savecoloursection"' in palette
    assert 'id="savecolours"' in mappings
    assert '$("savecoloursection").onclick=()=>$("savecolours").click()' in HTML
    assert '$("discardcoloursection").onclick=()=>$("discardcolours").click()' in HTML
    assert 'for(const id of ["dirtyhint","dirtyhintcolours"])' in HTML
    assert 'request("/manage/colours",{value:{colours:value,renames,priority:[...priorityOrder],events}})' in HTML


def test_council_existing_calendar_titles_are_matched_semantically(monkeypatch, tmp_path):
    from bindicator.web import Management
    from bindicator import north_yorkshire
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""calendar:
  events:
    'BinDay – Recycling': blue
    'BinDay – Household waste': orange
    'BinDay – Garden Waste': green
hue:
  bridges: {}
  lights: []
  mode: priority
colors:
  blue: {x: 0.17, y: 0.08}
  orange: {x: 0.57, y: 0.39}
  green: {x: 0.21, y: 0.65}
priority: [orange, blue, green]
""")
    records = [
        {"date": "2030-01-01", "title": "BinDay - Recycling", "type": "Recycling"},
        {"date": "2030-01-08", "title": "BinDay - Household waste", "type": "Household waste"},
        {"date": "2030-01-08", "title": "BinDay - Garden Waste", "type": "Garden waste"},
    ]
    monkeypatch.setattr(north_yorkshire, "fetch_collections", lambda uprn: records)
    mgr = Management(config_path, tmp_path / "secrets.env", tmp_path)
    results = mgr.check_north_yorkshire({"uprn": "12345678901"})
    assert all(entry["mapped"] for entry in results["entries"])
    assert all(" – " in entry["title"] for entry in results["entries"])
    mgr.change("north_yorkshire", {"uprn": "12345678901", "enabled": True, "refresh_days": 7})
    from bindicator.app import Bindicator, collection_events_in_range
    from datetime import date
    config = mgr._config()
    data = Bindicator(config, tmp_path).calendar_data()
    events = collection_events_in_range(
        data, date(2029, 12, 31), date(2030, 1, 10), config["calendar"]["events"])
    assert {event["colour"] for event in events[date(2030, 1, 8)]} == {"orange", "green"}


def test_event_mapping_multi_select_uses_all_configured_sources():
    assert 'id="refreshevents"' in HTML
    assert 'id="eventrows" class="event-groups"' in HTML
    assert 'function renderEventMappings(openColour=null)' in HTML
    assert 'function refreshCalendarEventOptions()' in HTML or 'async function refreshCalendarEventOptions()' in HTML
    assert 'request("/manage/calendar-events")' in HTML
    assert 'check.onchange=()=>{' in HTML
    assert 'eventAssignments[title]=colour' in HTML
    assert 'delete eventAssignments[title]' in HTML
    assert 'eventAssignments=Object.fromEntries(v.events.map(e=>[e.name,e.colour]))' in HTML
    assert 'const events={};' in HTML
    assert 'Object.entries(eventAssignments)' in HTML
    assert 'eventColourName(previousColour)' in HTML
    assert 'event-chip' in HTML and 'event-picker' in HTML
    assert 'Custom event title' in HTML
    assert 'id="addevent"' not in HTML
    assert 'function addEvent(' not in HTML


def test_calendar_event_discovery_returns_all_source_titles_without_private_ids(
    monkeypatch, tmp_path
):
    from bindicator.web import Management
    from bindicator import north_yorkshire
    from bindicator.app import Bindicator
    from icalendar import Calendar, Event
    from datetime import date

    config_path = tmp_path / "config.yaml"
    config_path.write_text("""calendar:
  events:
    'BinDay – Recycling': blue
hue:
  bridges: {}
  lights: []
  mode: priority
colors:
  blue: {x: 0.17, y: 0.08}
priority: [blue]
north_yorkshire:
  enabled: false
  uprn: '12345678901'
""")
    secrets = tmp_path / "secrets.env"
    secrets.write_text('BINDICATOR_ICAL_URL="https://calendar.zoho.com/example"\\n')
    cal = Calendar()
    cal.add("prodid", "-//Test//EN")
    cal.add("version", "2.0")
    event = Event()
    event.add("summary", "Recycling Collection")
    event.add("dtstart", date(2030, 1, 1))
    cal.add_component(event)
    monkeypatch.setattr(Bindicator, "zoho_calendar_data", lambda self: cal.to_ical())
    monkeypatch.setattr(north_yorkshire, "fetch_collections", lambda uprn: [{
        "date": "2030-01-08", "title": "BinDay - Garden Waste", "type": "Garden waste"
    }])
    manager = Management(config_path, secrets, tmp_path)
    found = manager.calendar_event_options()
    events = {row["title"]: row["sources"] for row in found["events"]}
    assert "Recycling Collection" in events and "iCalendar" in events["Recycling Collection"]
    assert "BinDay - Garden Waste" in events and "North Yorkshire Council" in events["BinDay - Garden Waste"]
    assert "BinDay – Recycling" in events and "Saved mapping" in events["BinDay – Recycling"]
    assert not found["warnings"]
    assert "12345678901" not in repr(found)
    assert "calendar.zoho.com" not in repr(found)


def test_calendar_event_discovery_degrades_to_saved_mappings(monkeypatch, tmp_path):
    from bindicator.web import Management
    from bindicator import north_yorkshire
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""calendar:
  events:
    'BinDay – Recycling': blue
hue:
  bridges: {}
  lights: []
  mode: priority
colors:
  blue: {x: 0.17, y: 0.08}
priority: [blue]
north_yorkshire:
  enabled: false
  uprn: '12345678901'
""")
    monkeypatch.setattr(north_yorkshire, "fetch_collections", lambda uprn: (_ for _ in ()).throw(ValueError("Offline")))
    found = Management(config_path, tmp_path / "missing.env", tmp_path).calendar_event_options()
    assert found["warnings"] == ["North Yorkshire Council unavailable"]
    assert found["events"] == [{"title": "BinDay – Recycling", "sources": ["Saved mapping"]}]


def test_status_uses_original_council_style_wheelie_bin_icons():
    assert 'function binCategory(title)' in HTML
    assert 'function binCollectionIcon(title)' in HTML
    assert 'function collectionIcons(collections)' in HTML
    assert 'function renderNextCollection(upcoming)' in HTML
    assert 'box.append(collectionIcons(item.collections))' in HTML
    assert 'collectionIcons(item.collections),' in HTML  # Upcoming collection rows.
    assert 'renderNextCollection(upcoming);' in HTML
    assert 'svg.setAttribute("aria-hidden","true")' in HTML
    assert 'svg.setAttribute("focusable","false")' in HTML
    assert 'document.createElementNS(ns,"svg")' in HTML
    assert 'shape("path"' in HTML
    assert '.bin-collection-icons{display:flex' in HTML
    assert '.bin-collection-item{display:inline-flex' in HTML
    assert '.bin-collection-icon{width:39px;height:48px' in HTML
    for label in ('"garden"', '"recycling"', '"household"'):
        assert label in HTML


def test_shared_refresh_interval_and_status_are_wired():
    for field in ('id="calendarinterval"', 'id="refreshactive"',
                  'id="activecalendarupdated"', 'id="activecalendarstate"'):
        assert field in HTML
    assert 'request("/manage/calendar/refresh",{})' in HTML
    assert 'request("/manage/calendar-refresh",{days})' in HTML
    assert 'active.last_success' in HTML
    assert 'active.next_due' in HTML
    assert 'active.stale' in HTML


def test_collection_types_and_colours_have_same_display_order():
    assert '(item.display_colours||item.colours).join(", ")' in HTML
    assert 'collectionIcons(item.collections)' in HTML


def test_all_eight_tabs_have_the_requested_order_and_distinct_controls():
    names = ("status", "testing", "lighting", "colours", "calendars", "mapping", "help", "coffee")
    tab_positions = [HTML.index('id="tab-'+name+'"') for name in names]
    assert tab_positions == sorted(tab_positions)
    for name in names:
        assert 'id="panel-'+name+'"' in HTML
        assert 'aria-controls="panel-'+name+'"' in HTML
        assert 'aria-labelledby="tab-'+name+'"' in HTML
        assert '$("tab-'+name+'").onclick=()=>openTab("'+name+'")' in HTML
    assert 'nav{display:flex;flex-wrap:wrap' in HTML
    assert 'if(name==="mapping"&&!mappingLoaded)' in HTML
    panels = {}
    for name, next_name in zip(names, names[1:]+(None,)):
        content = HTML.split('id="panel-'+name+'"', 1)[1]
        panels[name] = content.split('id="panel-'+next_name+'"', 1)[0] if next_name else content.split('<footer>', 1)[0]
    for title in ("Hue Bridges", "Indicator lights", "Reminder timing", "Display settings"):
        assert '<summary>'+title+'</summary>' in panels["lighting"]
    assert '<summary>Indicator colours</summary>' in panels["colours"]
    assert '<summary>Calendar event mappings</summary>' in panels["mapping"]
    for title in ("North Yorkshire Council", "iCalendar (iCal)"):
        assert '<summary>'+title+'</summary>' in panels["calendars"]
    for identifier, panel in (
        ('id="colourrows"', "colours"),
        ('id="eventrows"', "mapping"),
        ('id="counciluprn"', "calendars"),
        ('id="calendarurl"', "calendars"),
        ('id="scanlights"', "lighting"),
    ):
        assert identifier in panels[panel]
        for other in names:
            if other != panel:
                assert identifier not in panels[other]


def test_calendar_api_shared_interval_and_provider_switch(monkeypatch, tmp_path):
    from bindicator.web import Management
    from bindicator.app import load_config
    from bindicator import north_yorkshire
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""calendar:
  events: {'BinDay - Recycling': blue}
hue: {bridges: {}, lights: [], mode: priority}
colors: {blue: {x: 0.17, y: 0.08}}
priority: [blue]
north_yorkshire: {enabled: false, uprn: '12345678901', refresh_days: 7}
""")
    secrets = tmp_path / "secrets.env"
    secrets.write_text('BINDICATOR_ICAL_URL="https://calendar.zoho.com/ical/private/test"\n')
    manager = Management(config_file, secrets, tmp_path)
    assert manager.overview()["active_calendar_source"] == "ical"
    manager.change("calendar_refresh", {"days": 14})
    assert load_config(config_file)["calendar_refresh"]["days"] == 14
    assert manager.overview()["calendar_refresh_days"] == 14
    records = [{"date": "2030-01-01", "title": "BinDay - Recycling", "type": "Recycling"}]
    monkeypatch.setattr(north_yorkshire, "fetch_collections", lambda _: records)
    manager.change("calendar_source", {"source": "council"})
    assert manager.overview()["active_calendar_source"] == "council"
    assert load_config(config_file)["calendar_refresh"]["days"] == 14
    manager.change("calendar_source", {"source": "ical"})
    assert manager.overview()["active_calendar_source"] == "ical"
    with pytest.raises(ValueError, match="1–90"):
        manager.change("calendar_refresh", {"days": 0})


def test_source_preview_council_returns_next_dates_not_only_connection(monkeypatch, tmp_path):
    from bindicator.web import Management
    from bindicator import north_yorkshire
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""calendar:
  events: {'BinDay - Recycling': blue}
hue: {bridges: {}, lights: [], mode: priority}
colors: {blue: {x: 0.17, y: 0.08}}
priority: [blue]
north_yorkshire: {enabled: false, uprn: '12345678901', refresh_days: 7}
""")
    monkeypatch.setattr(north_yorkshire, "fetch_collections", lambda _: [
        {"date": "2030-01-01", "title": "BinDay - Recycling", "type": "Recycling"},
        {"date": "2030-01-08", "title": "BinDay - Recycling", "type": "Recycling"},
    ])
    mgr = Management(config_file, tmp_path / "secrets.env", tmp_path)
    checked = mgr.check_calendar_source({"source": "council", "preview": False})
    preview = mgr.check_calendar_source({"source": "council", "preview": True})
    assert checked["ok"] and checked["dates"] == []
    assert preview["dates"][0] == {"date": "2030-01-01", "collections": ["Recycling"]}
    assert preview["count"] == 2


def test_help_and_coffee_tabs_include_actual_links_and_installed_version():
    assert 'id="tab-help"' in HTML
    assert 'id="tab-coffee"' in HTML
    help_panel = HTML.split('id="panel-help"', 1)[1].split('id="panel-coffee"', 1)[0]
    coffee_panel = HTML.split('id="panel-coffee"', 1)[1].split('<footer>', 1)[0]
    for url in (
        "https://github.com/accidentalskeleton/bindicator",
        "https://github.com/accidentalskeleton/bindicator/issues",
        "https://github.com/accidentalskeleton/bindicator/releases",
        "https://github.com/accidentalskeleton/bindicator/blob/main/docs/README.md",
    ):
        assert url in help_panel
    assert 'id="bindicatorversion"' in help_panel
    assert '$("bindicatorversion").textContent=v.application_version||"unknown"' in HTML
    assert 'https://buymeacoffee.com/stuliet' in coffee_panel
    assert 'Enjoying Bindicator?' in coffee_panel
    assert 'target="_blank" rel="noopener noreferrer"' in coffee_panel
    assert 'id="tab-help"' not in coffee_panel


def test_management_overview_reports_installed_package_version(tmp_path):
    from bindicator.web import Management
    from importlib.metadata import version
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""calendar:
  events: {'BinDay - Recycling': blue}
hue: {bridges: {}, lights: [], mode: priority}
colors: {blue: {x: 0.17, y: 0.08}}
priority: [blue]
""")
    secrets = tmp_path / "secrets.env"
    secrets.write_text("")
    result = Management(config_file, secrets, tmp_path).overview()
    assert result["application_version"] == version("bindicator")
    assert "coffee" not in result
