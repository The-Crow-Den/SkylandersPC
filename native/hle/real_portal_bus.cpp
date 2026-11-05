// SPDX-License-Identifier: GPL-3.0-or-later
#include "real_portal_bus.hpp"
#include "../thread_context.hpp"
#include <libusb.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <deque>
#include <map>
#include <mutex>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace RealPortalBus {
namespace {
using U = std::uint64_t;
using namespace PortalDevice;
struct Contract { std::string_view identity, name; };
constexpr Contract contracts[]{
#include "usb_contracts.inc"
};
std::string_view name(std::string_view identity) {
    for (const auto& item : contracts) if (identity == item.identity) return item.name;
    return {};
}
U error(unsigned value) { return 0x80240000u + value; }  // libusb error, negated.

// libusb structures rebuilt from the device's raw configuration descriptor.
struct Configuration {
    libusb_config_descriptor config{};
    std::vector<libusb_interface> interfaces;
    std::vector<std::vector<libusb_interface_descriptor>> alternates;
    std::vector<std::vector<std::vector<libusb_endpoint_descriptor>>> endpoints;
    std::vector<std::vector<std::vector<std::uint8_t>>> extras;
};
std::unique_ptr<Configuration> parse_configuration(std::span<const std::uint8_t> raw) {
    if (raw.size() < 9 || raw[1] != LIBUSB_DT_CONFIG) return nullptr;
    auto c = std::make_unique<Configuration>();
    std::memcpy(&c->config, raw.data(), 8); c->config.MaxPower = raw[8];
    const auto total = static_cast<unsigned>(std::min<std::size_t>(raw[2] | (raw[3] << 8), raw.size()));
    std::map<unsigned, unsigned> numbers;
    for (unsigned at = raw[0]; at + 2 <= total && raw[at] >= 2 && at + raw[at] <= total; at += raw[at]) {
        const auto* d = raw.data() + at;
        if (d[1] == LIBUSB_DT_INTERFACE && d[0] >= 9) {
            const auto [slot, added] = numbers.emplace(d[2], static_cast<unsigned>(numbers.size()));
            if (added) { c->alternates.emplace_back(); c->endpoints.emplace_back(); c->extras.emplace_back(); }
            libusb_interface_descriptor alt{};
            std::memcpy(&alt, d, 9);
            c->alternates[slot->second].push_back(alt);
            c->endpoints[slot->second].emplace_back(); c->extras[slot->second].emplace_back();
        } else if (!c->alternates.empty()) {
            const unsigned i = static_cast<unsigned>(c->alternates.size() - 1);
            if (d[1] == LIBUSB_DT_ENDPOINT && d[0] >= 7) {
                libusb_endpoint_descriptor endpoint{};
                endpoint.bLength = d[0]; endpoint.bDescriptorType = d[1]; endpoint.bEndpointAddress = d[2];
                endpoint.bmAttributes = d[3]; endpoint.wMaxPacketSize = static_cast<std::uint16_t>(d[4] | (d[5] << 8));
                endpoint.bInterval = d[6];
                c->endpoints[i].back().push_back(endpoint);
            } else if (c->endpoints[i].back().empty()) {
                c->extras[i].back().insert(c->extras[i].back().end(), d, d + d[0]);  // e.g. the HID descriptor.
            }
        }
    }
    for (unsigned i = 0; i < c->alternates.size(); ++i)
        for (unsigned a = 0; a < c->alternates[i].size(); ++a) {
            auto& alt = c->alternates[i][a];
            alt.endpoint = c->endpoints[i][a].data(); alt.bNumEndpoints = static_cast<std::uint8_t>(c->endpoints[i][a].size());
            alt.extra = c->extras[i][a].data(); alt.extra_length = static_cast<int>(c->extras[i][a].size());
        }
    for (auto& alts : c->alternates) c->interfaces.push_back({alts.data(), static_cast<int>(alts.size())});
    c->config.interface = c->interfaces.data();
    c->config.bNumInterfaces = static_cast<std::uint8_t>(c->interfaces.size());
    return c;
}

struct State {
    std::mutex mutex;
    std::function<std::unique_ptr<Transport>()> opener;
    std::filesystem::path backups;
    bool allow_writes = false, configured = false;
    std::unique_ptr<Transport> device;
    bool initialized = false, opened = false;
    unsigned char device_token = 0, handle_token = 0;
    std::unordered_set<void**> lists;
    std::unordered_set<Configuration*> configurations;
    std::unordered_set<libusb_transfer*> transfers;
    std::deque<libusb_transfer*> pending;
    std::deque<Report> stash;  // Reports read while backing up a figure.
    std::array<std::optional<std::array<std::uint8_t, 4>>, slots> slot_uid;
    std::set<std::array<std::uint8_t, 4>> backed_up;
    libusb_device* usb_device() { return reinterpret_cast<libusb_device*>(&device_token); }
    libusb_device_handle* usb_handle() { return reinterpret_cast<libusb_device_handle*>(&handle_token); }
};
State& state() { static State value; return value; }

std::span<const std::uint8_t> raw_device(const Info& info) {
    return info.usb_descriptors.size() >= 18 ? std::span(info.usb_descriptors).first(18) : std::span<const std::uint8_t>{};
}
std::span<const std::uint8_t> raw_config(const Info& info, unsigned index) {
    std::span<const std::uint8_t> rest(info.usb_descriptors);
    if (rest.size() < 18) return {};
    rest = rest.subspan(18);
    for (unsigned i = 0; rest.size() >= 9; ++i) {
        const std::size_t total = std::min<std::size_t>(rest[2] | (rest[3] << 8), rest.size());
        if (i == index) return rest.first(total);
        if (total < 9) break;
        rest = rest.subspan(total);
    }
    return {};
}

void note_status(State& s, std::span<const std::uint8_t> report) {
    if (const auto status = parse_status(report))
        for (unsigned slot = 0; slot < slots; ++slot)
            if (status->state[slot] != SlotState::present) s.slot_uid[slot].reset();
}
// Reads until a reply with the given first byte, stashing everything else so
// the game still receives it.
std::optional<Report> await(State& s, std::uint8_t kind, unsigned slot, unsigned block) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(1);
    while (std::chrono::steady_clock::now() < deadline) {
        Report reply{};
        const int count = s.device->read_report(reply, 50);
        if (count < 0) return std::nullopt;
        if (!count) continue;
        if (reply[0] == kind && (reply[1] & 15) == slot && reply[2] == block) return reply;
        s.stash.push_back(reply);
    }
    return std::nullopt;
}
bool backup_folder_ready(const std::filesystem::path& folder) {
    std::error_code ec;
    std::filesystem::create_directories(folder, ec);
    if (ec) return false;
    std::filesystem::permissions(folder, std::filesystem::perms::owner_all, ec);
    return !ec;
}
// Reads the whole figure through the portal and saves it privately before the
// game's first write to it. A figure that cannot be backed up is not written.
bool back_up(State& s, unsigned slot) {
    std::vector<std::uint8_t> figure;
    for (unsigned block = 0; block < figure_blocks; ++block) {
        if (!s.device->write_report(query(slot, block))) return false;
        const auto reply = await(s, 'Q', slot, block);
        const auto parsed = reply ? parse_query(*reply) : std::nullopt;
        if (!parsed || !parsed->ok) return false;
        figure.insert(figure.end(), parsed->data.begin(), parsed->data.end());
    }
    const std::array<std::uint8_t, 4> uid{figure[0], figure[1], figure[2], figure[3]};
    s.slot_uid[slot] = uid;
    if (s.backed_up.contains(uid)) return true;
    if (!backup_folder_ready(s.backups)) return false;
    char file[64];
    std::snprintf(file, sizeof(file), "%02x%02x%02x%02x-%lld.sky", uid[0], uid[1], uid[2], uid[3], static_cast<long long>(std::time(nullptr)));
    const auto path = s.backups / file;
    const int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0) return false;
    const bool written = ::write(fd, figure.data(), figure.size()) == static_cast<ssize_t>(figure.size());
    const bool closed = ::close(fd) == 0;
    if (!written || !closed) { std::filesystem::remove(path); return false; }
    s.backed_up.insert(uid);
    std::printf("Real portal: backed up the figure in slot %u before its first write\n", slot);
    return true;
}
// Sends a report from the game. Figure writes are opt-in and backed up first.
bool send(State& s, std::span<const std::uint8_t> report) {
    if (const auto target = write_target(report)) {
        if (!s.allow_writes) {
            static unsigned told = 0;
            if (told++ < 4) std::fprintf(stderr, "Real portal: figure write refused; set SKY_PORTAL_FIGURE_WRITES=1 to allow writes\n");
            return false;
        }
        const auto slot = target->first;
        if (!s.slot_uid[slot] || !s.backed_up.contains(*s.slot_uid[slot])) {
            if (!back_up(s, slot)) { std::fprintf(stderr, "Real portal: figure backup failed; write refused\n"); return false; }
        }
    }
    return s.device->write_report(report);
}
int receive(State& s, std::span<std::uint8_t> output, int timeout_ms) {
    if (!s.stash.empty()) {
        const auto report = s.stash.front(); s.stash.pop_front();
        const auto count = std::min(output.size(), report.size());
        std::copy_n(report.begin(), count, output.begin());
        return static_cast<int>(count);
    }
    const int count = s.device->read_report(output, timeout_ms);
    if (count > 0) note_status(s, output.first(static_cast<std::size_t>(count)));
    return count;
}

int control(State& s, unsigned type, unsigned request, unsigned value, unsigned index, unsigned char* data, int length) {
    if (length < 0 || length > 4096 || (!data && length)) return LIBUSB_ERROR_INVALID_PARAM;
    const auto& info = s.device->info();
    if (request == LIBUSB_REQUEST_GET_DESCRIPTOR && (type & 0x80)) {
        std::span<const std::uint8_t> source;
        if (value >> 8 == LIBUSB_DT_DEVICE) source = raw_device(info);
        else if (value >> 8 == LIBUSB_DT_CONFIG) source = raw_config(info, value & 255);
        else if (value >> 8 == LIBUSB_DT_REPORT) source = info.report_descriptor;
        if (source.empty()) return LIBUSB_ERROR_PIPE;  // String descriptors are not available through hidraw.
        const int count = std::min<int>(length, static_cast<int>(source.size()));
        std::memcpy(data, source.data(), static_cast<std::size_t>(count));
        return count;
    }
    if (request == 9 && !(type & 0x80)) return send(s, {data, static_cast<std::size_t>(length)}) ? length : LIBUSB_ERROR_IO;
    if (request == 1 && (type & 0x80)) {
        const int count = receive(s, {data, static_cast<std::size_t>(length)}, 20);
        return count < 0 ? LIBUSB_ERROR_NO_DEVICE : count;
    }
    // SET_IDLE and SET_PROTOCOL: the host HID driver configured the device
    // when it bound; hidraw cannot repeat them.
    if ((request == 10 || request == 11) && !(type & 0x80) && !length) return 0;
    (void)index;
    return LIBUSB_ERROR_NOT_SUPPORTED;
}

std::filesystem::path default_backups() {
    const auto* data_home = std::getenv("XDG_DATA_HOME");
    const auto* home = std::getenv("HOME");
    std::filesystem::path base;
    if (data_home && std::filesystem::path(data_home).is_absolute()) base = data_home;
    else if (home && std::filesystem::path(home).is_absolute()) base = std::filesystem::path(home) / ".local/share";
    else return {};
    return base / "skylanders-pc/portal-backups";
}
}

bool enabled() {
    if (state().configured) return true;
    const auto* device = std::getenv("SKY_PORTAL_DEVICE");
    const auto* virtual_portal = std::getenv("SKY_VIRTUAL_PORTAL");
    return device && *device && !(virtual_portal && std::strcmp(virtual_portal, "1") == 0);
}
bool supports(std::string_view identity) { return enabled() && !name(identity).empty(); }
unsigned stack_arguments(std::string_view identity) {
    const auto api = name(identity);
    return api == "ControlTransfer" || api == "FillInterruptTransfer" ? 2 : 0;
}
void configure(std::function<std::unique_ptr<Transport>()> opener, std::filesystem::path folder, bool allow) {
    auto& s = state();
    std::lock_guard guard(s.mutex);
    s.opener = std::move(opener); s.backups = std::move(folder); s.allow_writes = allow; s.configured = true;
    s.device.reset(); s.initialized = s.opened = false; s.stash.clear(); s.backed_up.clear(); s.slot_uid = {};
}

std::uint64_t call(std::string_view identity, const std::uint64_t* a) {
    auto& s = state();
    const auto api = name(identity);
    if (api.empty()) throw std::runtime_error("unsupported real-portal USB import");
    std::unique_lock lock(s.mutex);
    if (api == "Init") {
        if (!s.device) {
            if (!s.configured) {
                const std::string id = std::getenv("SKY_PORTAL_DEVICE");
                s.opener = [id] { return PortalDevice::open(id); };
                s.backups = default_backups();
                const auto* writes = std::getenv("SKY_PORTAL_FIGURE_WRITES");
                s.allow_writes = writes && std::strcmp(writes, "1") == 0;
            }
            s.device = s.opener ? s.opener() : nullptr;
            if (!s.device) { std::fprintf(stderr, "Real portal: no portal could be opened\n"); return error(4); }
            const auto& info = s.device->info();
            if (info.family != Family::hid)
                std::fprintf(stderr, "Real portal: %s portals use a different USB identity than the PS4 game looks for\n", family_name(info.family));
            if (raw_device(info).empty()) { std::fprintf(stderr, "Real portal: the device's USB descriptors are unavailable\n"); s.device.reset(); return error(4); }
            std::printf("Real portal: %s (%04x:%04x) at %s\n", info.name.c_str(), info.vendor, info.product, info.id.c_str());
        }
        s.initialized = true; return 0;
    }
    if (api == "FreeDeviceList") {
        auto** list = reinterpret_cast<void**>(a[0]);
        if (list && !s.lists.erase(list)) throw std::runtime_error("unknown USB list ownership");
        delete[] list; return 0;
    }
    if (api == "Exit") {
        if (!s.pending.empty()) throw std::runtime_error("USB exit with pending transfers");
        s.opened = s.initialized = false; return 0;
    }
    if (!s.initialized) return error(99);
    auto* device = s.usb_device();
    auto* handle = s.usb_handle();
    if (api == "GetDeviceList") {
        if (!a[0]) return error(2);
        auto** list = new void*[2]{device, nullptr};
        s.lists.insert(list); *reinterpret_cast<void***>(a[0]) = list; return 1;
    }
    if (api == "GetDeviceDescriptor") {
        if (a[0] != reinterpret_cast<U>(device) || !a[1]) return error(2);
        std::memcpy(reinterpret_cast<void*>(a[1]), raw_device(s.device->info()).data(), 18); return 0;
    }
    if (api == "GetBusNumber" || api == "GetDeviceAddress") return a[0] == reinterpret_cast<U>(device) ? 1 : 0;
    if (api == "GetConfigDescriptor") {
        if (a[0] != reinterpret_cast<U>(device) || !a[2]) return error(2);
        auto parsed = parse_configuration(raw_config(s.device->info(), static_cast<unsigned>(a[1])));
        if (!parsed) return error(5);
        auto* config = parsed.release(); s.configurations.insert(config);
        *reinterpret_cast<libusb_config_descriptor**>(a[2]) = &config->config; return 0;
    }
    if (api == "FreeConfigDescriptor") {
        auto* config = reinterpret_cast<Configuration*>(a[0]);
        if (config && !s.configurations.erase(config)) throw std::runtime_error("unknown USB config ownership");
        delete config; return 0;
    }
    if (api == "OpenDeviceWithVidPid") {
        const auto& info = s.device->info();
        if (a[0] != info.vendor || a[1] != info.product) return 0;
        s.opened = true; return reinterpret_cast<U>(handle);
    }
    if (api == "Open") {
        if (a[0] != reinterpret_cast<U>(device) || !a[1]) return error(2);
        s.opened = true; *reinterpret_cast<libusb_device_handle**>(a[1]) = handle; return 0;
    }
    if (api == "AllocTransfer") {
        const auto packets = static_cast<int>(a[0]);
        if (packets < 0 || packets > 64) return 0;
        auto* t = libusb_alloc_transfer(packets);
        if (t) s.transfers.insert(t);
        return reinterpret_cast<U>(t);
    }
    if (api == "FreeTransfer") {
        auto* t = reinterpret_cast<libusb_transfer*>(a[0]);
        if (std::find(s.pending.begin(), s.pending.end(), t) != s.pending.end()) throw std::runtime_error("free pending USB transfer");
        if (!s.transfers.erase(t)) throw std::runtime_error("unknown USB transfer ownership");
        libusb_free_transfer(t); return 0;
    }
    if (api == "FillInterruptTransfer" || api == "SubmitTransfer" || api == "CancelTransfer") {
        auto* t = reinterpret_cast<libusb_transfer*>(a[0]);
        if (!s.transfers.contains(t)) return error(2);
        if (api == "FillInterruptTransfer") {
            t->dev_handle = reinterpret_cast<libusb_device_handle*>(a[1]); t->endpoint = static_cast<unsigned char>(a[2]);
            t->type = LIBUSB_TRANSFER_TYPE_INTERRUPT;
            t->buffer = reinterpret_cast<unsigned char*>(a[3]); t->length = static_cast<int>(a[4]);
            t->callback = reinterpret_cast<libusb_transfer_cb_fn>(a[5]); t->user_data = reinterpret_cast<void*>(a[6]);
            t->timeout = static_cast<unsigned>(a[7]); return 0;
        }
        const auto queued = std::find(s.pending.begin(), s.pending.end(), t);
        if (api == "CancelTransfer") {
            if (queued == s.pending.end()) return error(5);
            t->status = LIBUSB_TRANSFER_CANCELLED; return 0;
        }
        if (queued != s.pending.end()) return error(6);
        if (!s.opened || t->dev_handle != handle) return error(4);
        if (t->flags & (LIBUSB_TRANSFER_FREE_BUFFER | LIBUSB_TRANSFER_FREE_TRANSFER)) return error(12);
        if (!t->buffer || t->length < 0 || t->length > 1024 || t->type != LIBUSB_TRANSFER_TYPE_INTERRUPT) return error(2);
        t->status = LIBUSB_TRANSFER_COMPLETED; t->actual_length = 0; s.pending.push_back(t); return 0;
    }
    if (api == "HandleEvents" || api == "HandleEventsTimeout") {
        if (s.pending.empty()) { lock.unlock(); std::this_thread::sleep_for(std::chrono::milliseconds(1)); return 0; }
        auto* t = s.pending.front(); s.pending.pop_front();
        if (t->status != LIBUSB_TRANSFER_CANCELLED) {
            std::span<std::uint8_t> buffer(t->buffer, static_cast<std::size_t>(t->length));
            if (t->endpoint & 0x80) {
                const int count = receive(s, buffer, 4);
                // Nothing arrived yet: the transfer stays pending, as on real hardware.
                if (!count) { s.pending.push_back(t); lock.unlock(); std::this_thread::sleep_for(std::chrono::milliseconds(1)); return 0; }
                if (count < 0) { t->status = LIBUSB_TRANSFER_NO_DEVICE; std::fprintf(stderr, "Real portal: device stopped responding\n"); }
                else t->actual_length = count;
            } else {
                // Trap Team portals take 64-byte speaker PCM on the OUT endpoint
                // and accept 32-byte reports there too.
                const bool ok = t->length == 64 ? s.device->write_audio(buffer) : send(s, buffer);
                if (ok) t->actual_length = t->length; else t->status = LIBUSB_TRANSFER_ERROR;
            }
        }
        const auto callback = reinterpret_cast<U>(t->callback);
        lock.unlock();
        if (callback) {
            auto* context = GuestThreadContext::current();
            if (!context) throw std::runtime_error("USB callback outside guest thread");
            context->callback(callback, t);
        }
        return 0;
    }
    if (!s.opened || a[0] != reinterpret_cast<U>(handle)) return error(4);
    if (api == "Close") { s.opened = false; return 0; }
    if (api == "CheckConnected") return 0;
    if (api == "KernelDriverActive") return 0;  // The host driver stays bound; hidraw sits beside it.
    if (api == "ClaimInterface" || api == "ReleaseInterface" || api == "AttachKernelDriver" || api == "DetachKernelDriver")
    {
        const auto config = parse_configuration(raw_config(s.device->info(), 0));
        return !config || a[1] >= config->config.bNumInterfaces ? error(5) : 0;
    }
    if (api == "ControlTransfer") {
        const int result = control(s, static_cast<unsigned char>(a[1]), static_cast<unsigned char>(a[2]),
            static_cast<std::uint16_t>(a[3]), static_cast<std::uint16_t>(a[4]), reinterpret_cast<unsigned char*>(a[5]), static_cast<int>(a[6]));
        if (result < 0) {
            static unsigned rejected = 0;
            if (rejected++ < 8) std::fprintf(stderr, "Real portal: control type=%02x request=%u value=%04x length=%u failed (%d)\n",
                unsigned(a[1] & 255), unsigned(a[2] & 255), unsigned(a[3] & 65535), unsigned(a[6]), result);
            return error(static_cast<unsigned>(-result));
        }
        return static_cast<U>(result);
    }
    throw std::runtime_error("real portal operation unavailable: " + std::string(api));
}
}
