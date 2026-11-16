--[[
    Dolby Vision Profile 5 (IPTPQc2) to Rec.709 SDR Auto-Tonemapper
    For mpv & IINA (scripts directory)
    Developed by BOOB Player Team
]]--

local mp = require 'mp'
local utils = require 'mp.utils'

local is_applied = false
local original_props = {}
local shader_file = mp.find_config_file("shaders/dolby_vision_p5.glsl")

local function is_dv_p5()
    local colormatrix = string.lower(mp.get_property("video-params/colormatrix") or "")
    if string.find(colormatrix, "dolbyvision") or string.find(colormatrix, "dovi") or string.find(colormatrix, "ipt") then
        return true
    end

    local video_format = string.lower(mp.get_property("video-format") or "")
    if video_format == "dvh1" or video_format == "dvhe" then
        return true
    end

    local path = string.lower(mp.get_property("path") or "")
    local filename = string.lower(mp.get_property("filename") or "")
    local media_name = path .. " " .. filename
    if string.find(media_name, "dv.p5") or string.find(media_name, "dv_05") or 
       string.find(media_name, "profile.5") or string.find(media_name, "profile 5") or 
       string.find(media_name, "dovi.05") then
        return true
    end

    return false
end

local function apply_dv_tonemap()
    if is_applied then return end

    -- Save originals
    original_props["tone-mapping"] = mp.get_property("tone-mapping")
    original_props["target-prim"] = mp.get_property("target-prim")
    original_props["target-trc"] = mp.get_property("target-trc")
    original_props["target-peak"] = mp.get_property("target-peak")
    original_props["hdr-compute-peak"] = mp.get_property("hdr-compute-peak")
    original_props["gamut-mapping-mode"] = mp.get_property("gamut-mapping-mode")

    -- Apply optimal libplacebo DOVI RPU settings
    mp.set_property("target-prim", "bt.709")
    mp.set_property("target-trc", "auto")
    mp.set_property("target-peak", "auto")
    mp.set_property("tone-mapping", "clip")
    mp.set_property("gamut-mapping-mode", "clip")
    mp.set_property("hdr-compute-peak", "no")

    -- If shader is available, apply GLSL reshaper hook
    if shader_file then
        mp.commandv("change-list", "glsl-shaders", "append", shader_file)
    end

    is_applied = true
    mp.osd_message("💎 Dolby Vision P5 → Rec.709 SDR Applied", 2.5)
    mp.msg.info("[DV-Tonemap] Applied Profile 5 SDR mapping")
end

local function restore_props()
    if not is_applied then return end

    if shader_file then
        mp.commandv("change-list", "glsl-shaders", "remove", shader_file)
    end

    for prop, val in pairs(original_props) do
        if val then mp.set_property(prop, val) end
    end
    original_props = {}
    is_applied = false
    mp.msg.info("[DV-Tonemap] Restored default color pipeline")
end

local function on_file_loaded()
    if is_dv_p5() then
        apply_dv_tonemap()
    else
        restore_props()
    end
end

mp.register_event("file-loaded", on_file_loaded)
mp.observe_property("video-params", "native", function(_, val)
    if val then on_file_loaded() end
end)

mp.add_key_binding("Ctrl+Alt+d", "toggle_dv_tonemap", function()
    if is_applied then
        restore_props()
        mp.osd_message("DV Tonemap: Disabled", 2)
    else
        apply_dv_tonemap()
    end
end)
