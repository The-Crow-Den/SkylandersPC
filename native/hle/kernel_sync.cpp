// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_sync.hpp"
#include <array>
#include <cerrno>
#include <pthread.h>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <time.h>
#include <mutex>
#include <thread>
#include <vector>

namespace {
bool relative_mutex(std::string_view name) {
    return name == "IafI2PxcPnQ#libkernel#libkernel";
}
constexpr std::array<std::string_view, 21> identities{
    "F8bUHwAG284#libkernel#libkernel", // scePthreadMutexattrInit
    "iMp8QpE+XO4#libkernel#libkernel", // scePthreadMutexattrSettype
    "smWEktiyyG0#libkernel#libkernel", // scePthreadMutexattrDestroy
    "1FGvU0i9saQ#libkernel#libkernel", // scePthreadMutexattrSetprotocol
    "cmo1RIYva9o#libkernel#libkernel", // scePthreadMutexInit
    "9UK1vLZQft4#libkernel#libkernel", // scePthreadMutexLock
    "upoVrzMHFeE#libkernel#libkernel", // scePthreadMutexTrylock
    "tn3VlD0hG60#libkernel#libkernel", // scePthreadMutexUnlock
    "2Of0f+3mhhE#libkernel#libkernel", // scePthreadMutexDestroy
    "geDaqgH9lTg#libkernel#libkernel", // scePthreadKeyCreate
    "PrdHuuDekhY#libkernel#libkernel", // scePthreadKeyDelete
    "+BzXYkqYeLE#libkernel#libkernel", // scePthreadSetspecific
    "eoht7mQOCmo#libkernel#libkernel", // scePthreadGetspecific
    "m5-2bsNfv7s#libkernel#libkernel", // scePthreadCondattrInit
    "waPcxYiR3WA#libkernel#libkernel", // scePthreadCondattrDestroy
    "2Tb92quprl0#libkernel#libkernel", // scePthreadCondInit
    "g+PZd2hiacg#libkernel#libkernel", // scePthreadCondDestroy
    "WKAXJ4XBPQ4#libkernel#libkernel", // scePthreadCondWait
    "BmMjYxmew1w#libkernel#libkernel", // scePthreadCondTimedwait
    "kDh-NfxgMtE#libkernel#libkernel", // scePthreadCondSignal
    "JGgj7Uvrl+A#libkernel#libkernel", // scePthreadCondBroadcast
};
struct PosixAlias { std::string_view nid; std::size_t operation; };
constexpr std::array<PosixAlias, 14> posix_aliases{{
    {"dQHWEsJtoE4", 0}, {"mDmgMOGVUqg", 1}, {"HF7lK46xzjY", 2},
    {"ttHNfU+qDBU", 4}, {"ltCfaGr2JGE", 8}, {"7H0iTOciTLo", 5},
    {"K-jXhbt2gn4", 6}, {"2Z+PpY6CaJg", 7},
    {"0TyVk4MSLt0", 15}, {"RXXqi4CtF8w", 16}, {"Op8TBGY5KHg", 17},
    {"27bAgiJmOh0", 18}, {"2MOy+rUfuhQ", 19}, {"mkx2fVhNMsg", 20},
}};
std::size_t posix_operation(std::string_view identity) noexcept {
    const auto separator = identity.find('#');
    if (separator == std::string_view::npos) return identities.size();
    const auto suffix = identity.substr(separator);
    if (suffix != "#libScePosix#libkernel" && suffix != "#libkernel#libkernel") return identities.size();
    const auto nid = identity.substr(0, separator);
    for (const auto& alias : posix_aliases) if (alias.nid == nid) return alias.operation;
    return identities.size();
}
std::uint64_t error(int code) {
    if (!code) return 0;
    unsigned guest;
    switch (code) {
        case EPERM: guest = 1; break;
        case ENOMEM: guest = 12; break;
        case EBUSY: guest = 16; break;
        case EINVAL: guest = 22; break;
        case EDEADLK: guest = 11; break;
        case EAGAIN: guest = 35; break;
        case ENOTSUP: guest = 45; break;
        case ETIMEDOUT: guest = 60; break;
        default: throw std::runtime_error("unmapped mutex error");
    }
    return 0x80020000u | guest;
}
struct Mutex {
    pthread_mutex_t native;
    bool initialized = false;
    ~Mutex() { if (initialized) pthread_mutex_destroy(&native); }
};
struct Condition {
    pthread_cond_t native;
    bool initialized = false;
    unsigned waiters = 0;
    ~Condition() { if (initialized) pthread_cond_destroy(&native); }
};
}

struct KernelSync::Impl {
    std::mutex registry;
    std::uint64_t next = 0x53000000;
    std::unordered_map<std::uint64_t, int> attributes;
    std::unordered_map<std::uint64_t, std::shared_ptr<Mutex>> mutexes;
    struct Key { std::uint64_t destructor; std::unordered_map<std::thread::id, std::uint64_t> values; };
    std::unordered_map<std::uint32_t, Key> keys;
    std::uint32_t next_key = 0;
    std::unordered_set<std::uint64_t> condition_attributes;
    std::unordered_map<std::uint64_t, std::shared_ptr<Condition>> conditions;
};
KernelSync::KernelSync() : impl_(std::make_unique<Impl>()) {}
KernelSync::~KernelSync() = default;
void KernelSync::finish_thread(const std::function<void(std::uint64_t, std::uint64_t)>& callback) {
    const auto id = std::this_thread::get_id();
    for (unsigned pass = 0; pass < 4; ++pass) {
        std::vector<std::pair<std::uint64_t, std::uint64_t>> pending;
        {
            std::lock_guard lock(impl_->registry);
            for (auto& [key_id, key] : impl_->keys) {
                auto value = key.values.find(id);
                if (value == key.values.end()) continue;
                if (value->second && key.destructor) pending.emplace_back(key.destructor, value->second);
                key.values.erase(value);
            }
        }
        if (pending.empty()) break;
        for (const auto& [function, argument] : pending) callback(function, argument);
    }
    std::lock_guard lock(impl_->registry);
    for (auto& [key_id, key] : impl_->keys) key.values.erase(id);
}
bool KernelSync::supports(std::string_view identity) noexcept {
    if (relative_mutex(identity)) return true;
    if (posix_operation(identity) != identities.size()) return true;
    for (auto name : identities) if (name == identity) return true;
    return false;
}

std::uint64_t KernelSync::call(std::string_view identity, const std::uint64_t* args) {
    if (relative_mutex(identity)) {
        const auto result = call("internal-relative-mutex", args);
        return result ? result & 0xffff : 0;
    }
    const bool relative = identity == "internal-relative-mutex";
    if (relative) identity = identities[5];
    const auto posix = posix_operation(identity);
    if (posix != identities.size()) {
        const auto result = call(identities[posix], args);
        return result ? result & 0xffff : 0; // POSIX returns positive guest errno.
    }
    std::unique_lock registry_lock(impl_->registry);
    std::size_t operation = 0;
    while (operation < identities.size() && identities[operation] != identity) ++operation;
    if (operation == identities.size()) throw std::runtime_error("unsupported synchronization import");
    if (operation >= 13) {
        auto* handle = reinterpret_cast<std::uint64_t*>(args[0]);
        if (!handle) return error(EINVAL);
        if (operation == 13) {
            const auto id = impl_->next++;
            impl_->condition_attributes.insert(id); *handle = id; return 0;
        }
        if (operation == 14) {
            if (!impl_->condition_attributes.erase(*handle)) return error(EINVAL);
            *handle = 0; return 0;
        }
        if (operation == 15 || (*handle < 2 && operation >= 17)) {
            if (operation == 15 && args[1] && !impl_->condition_attributes.contains(
                    *reinterpret_cast<const std::uint64_t*>(args[1]))) return error(EINVAL);
            auto cond = std::make_shared<Condition>();
            const int status = pthread_cond_init(&cond->native, nullptr);
            if (status) return error(status);
            cond->initialized = true;
            const auto id = impl_->next++;
            impl_->conditions.emplace(id, std::move(cond)); *handle = id;
            if (operation == 15) return 0;
        }
        auto cond = impl_->conditions.find(*handle);
        if (cond == impl_->conditions.end()) return error(EINVAL);
        if (operation == 16) {
            if (cond->second->waiters) return error(EBUSY);
            const int status = pthread_cond_destroy(&cond->second->native);
            if (!status) { cond->second->initialized = false; impl_->conditions.erase(cond); *handle = 2; }
            return error(status);
        }
        if (operation == 19) return error(pthread_cond_signal(&cond->second->native));
        if (operation == 20) return error(pthread_cond_broadcast(&cond->second->native));
        if (!args[1]) return error(EINVAL);
        const auto mutex_id = *reinterpret_cast<const std::uint64_t*>(args[1]);
        auto mutex = impl_->mutexes.find(mutex_id);
        if (mutex == impl_->mutexes.end()) return error(EINVAL);
        auto cond_record = cond->second;
        auto mutex_record = mutex->second;
        ++cond_record->waiters;
        if (operation == 17) {
            registry_lock.unlock();
            const auto status = pthread_cond_wait(&cond_record->native, &mutex_record->native);
            registry_lock.lock(); --cond_record->waiters;
            return error(status);
        }
        timespec deadline{};
        if (clock_gettime(CLOCK_REALTIME, &deadline)) throw std::runtime_error("condition clock failed");
        const auto usec = static_cast<std::uint32_t>(args[2]);
        const auto ns = static_cast<std::uint64_t>(deadline.tv_nsec) + (usec % 1000000) * 1000ull;
        deadline.tv_sec += usec / 1000000 + static_cast<time_t>(ns / 1000000000);
        deadline.tv_nsec = static_cast<long>(ns % 1000000000);
        registry_lock.unlock();
        const auto status = pthread_cond_timedwait(&cond_record->native, &mutex_record->native, &deadline);
        registry_lock.lock(); --cond_record->waiters;
        return error(status);
    }
    if (operation >= 9) {
        if (operation == 9) {
            if (!args[0]) return error(EINVAL);
            if (impl_->keys.size() >= 256) return error(EAGAIN);
            const auto key = impl_->next_key++;
            impl_->keys.emplace(key, Impl::Key{args[1], {}});
            *reinterpret_cast<std::uint32_t*>(args[0]) = key;
            return 0;
        }
        auto key = impl_->keys.find(static_cast<std::uint32_t>(args[0]));
        if (key == impl_->keys.end()) return operation == 12 ? 0 : error(EINVAL);
        if (operation == 10) impl_->keys.erase(key);
        else if (operation == 11) key->second.values[std::this_thread::get_id()] = args[1];
        else {
            const auto value = key->second.values.find(std::this_thread::get_id());
            return value == key->second.values.end() ? 0 : value->second;
        }
        return 0;
    }
    auto* handle = reinterpret_cast<std::uint64_t*>(args[0]);
    if (!handle) return error(EINVAL);
    try {
        if (operation == 0) {
            const auto id = impl_->next++;
            impl_->attributes.emplace(id, 1); // Orbis default: error-checking mutex.
            *handle = id;
            return 0;
        }
        if (operation <= 3) {
            auto attr = impl_->attributes.find(*handle);
            if (attr == impl_->attributes.end()) return error(EINVAL);
            if (operation == 1) {
                if (args[1] < 1 || args[1] > 3) return error(EINVAL);
                attr->second = static_cast<int>(args[1]);
            } else if (operation == 2) {
                impl_->attributes.erase(attr);
                *handle = 0;
            } else {
                // Priority inheritance/protection requires a guest scheduler.
                if (args[1] > 2) return error(EINVAL);
                if (args[1] != 0) return error(ENOTSUP);
            }
            return 0;
        }
        const auto initialize = [&](int type) -> std::uint64_t {
            auto mutex = std::make_shared<Mutex>();
            pthread_mutexattr_t attr;
            int status = pthread_mutexattr_init(&attr);
            if (status) return error(status);
            const int native_type = type == 2 ? PTHREAD_MUTEX_RECURSIVE :
                                    type == 3 ? PTHREAD_MUTEX_NORMAL : PTHREAD_MUTEX_ERRORCHECK;
            status = pthread_mutexattr_settype(&attr, native_type);
            if (!status) status = pthread_mutex_init(&mutex->native, &attr);
            pthread_mutexattr_destroy(&attr);
            if (status) return error(status);
            mutex->initialized = true;
            const auto id = impl_->next++;
            impl_->mutexes.emplace(id, std::move(mutex));
            *handle = id;
            return 0;
        };
        if (operation == 4) {
            int type = 1;
            if (args[1]) {
                const auto id = *reinterpret_cast<const std::uint64_t*>(args[1]);
                auto attr = impl_->attributes.find(id);
                if (attr == impl_->attributes.end()) return error(EINVAL);
                type = attr->second;
            }
            return initialize(type);
        }
        // Zero/one represent static initializers; two is a destroyed handle.
        if (*handle < 2 && (operation == 5 || operation == 6)) {
            const auto status = initialize(1);
            if (status) return status;
        }
        auto mutex = impl_->mutexes.find(*handle);
        if (mutex == impl_->mutexes.end()) return error(EINVAL);
        if (operation >= 5 && operation <= 7) {
            auto record = mutex->second;
            registry_lock.unlock();
            if (relative) {
#ifdef _WIN32
                // winpthreads has no clocklock; its timedlock takes a realtime deadline.
                constexpr clockid_t deadline_clock = CLOCK_REALTIME;
#else
                constexpr clockid_t deadline_clock = CLOCK_MONOTONIC;
#endif
                timespec deadline{};
                if (clock_gettime(deadline_clock, &deadline)) throw std::runtime_error("mutex clock failed");
                const auto ns = static_cast<std::uint64_t>(deadline.tv_nsec) + (args[1] % 1000000) * 1000;
                deadline.tv_sec += args[1] / 1000000 + ns / 1000000000;
                deadline.tv_nsec = ns % 1000000000;
#ifdef _WIN32
                return error(pthread_mutex_timedlock(&record->native, &deadline));
#else
                return error(pthread_mutex_clocklock(&record->native, CLOCK_MONOTONIC, &deadline));
#endif
            }
            if (operation == 5) return error(pthread_mutex_lock(&record->native));
            if (operation == 6) return error(pthread_mutex_trylock(&record->native));
            return error(pthread_mutex_unlock(&record->native));
        }
        const int status = pthread_mutex_destroy(&mutex->second->native);
        if (!status) {
            mutex->second->initialized = false;
            impl_->mutexes.erase(mutex);
            *handle = 2;
        }
        return error(status);
    } catch (const std::bad_alloc&) { return error(ENOMEM); }
}
