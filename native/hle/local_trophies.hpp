// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Offline trophy contracts/layouts cross-checked against shadPS4's NpTrophy
// interface (GPL-2.0-or-later). Unlocks are recorded only on guest API
// requests.
#include "local_players.hpp"
#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <unistd.h>
#include <vector>

// Renderer popup (libskyrender); absent in tests and headless runs.
extern "C" void skyrender_show_toast(const char *, const char *, int)
    __attribute__((weak));

class LocalTrophies {
  using U = std::uint64_t;
  struct Item {
    int id, grade, group;
    bool hidden, unlocked;
    U timestamp;
    std::string name, detail;
  };
  struct Context {
    int user;
    bool registered = false;
  };
  struct TrophyDetails {
    U size;
    std::int32_t id, grade, group;
    bool hidden;
    unsigned char pad[3];
    char name[128], description[1024];
  };
  struct TrophyData {
    U size;
    std::int32_t id;
    bool unlocked;
    unsigned char pad[3];
    U timestamp;
  };
  struct GameDetails {
    U size;
    std::uint32_t groups, total, platinum, gold, silver, bronze;
    char name[128], description[1024];
  };
  struct GameData {
    U size;
    std::uint32_t total, platinum, gold, silver, bronze, percentage;
  };
  struct GroupDetails {
    U size;
    std::int32_t group;
    std::uint32_t total, platinum, gold, silver, bronze;
    char name[128], description[1024];
  };
  struct GroupData {
    U size;
    std::int32_t group;
    std::uint32_t total, platinum, gold, silver, bronze, percentage;
    unsigned char pad[4];
  };
  static_assert(sizeof(TrophyDetails) == 1176 && sizeof(TrophyData) == 24 &&
                sizeof(GameDetails) == 1184 && sizeof(GameData) == 32 &&
                sizeof(GroupDetails) == 1184 && sizeof(GroupData) == 40);
  static constexpr std::array<std::string_view, 14> nids{
      {"XbkjbobZlCY", "q7U6tEAQf7c", "E1Wrwd07Lr8", "GNcF4oidY0Y",
       "TJCAxto9SEU", "28xmRUFao68", "YYP3f2W09og", "qqUVGDgQBm0",
       "HLwz1fRIycA", "eBL+l6HG9xk", "w4uMPmErD4I", "wTUwGfspKic",
       "LHuSmO3SLd8", "aTnHs7W-9Uk"}};
  std::mutex mutex_;
  std::map<int, Context> contexts_;
  std::set<int> handles_;
  std::map<int, std::vector<Item>> users_;
  std::filesystem::path store_, catalogues_, icons_;
  std::string npwr_, title_;
  int next_context_ = 1, next_handle_ = 1;
  static constexpr U invalid_argument = 0x80551604, invalid_handle = 0x80551608,
                     invalid_context = 0x80551609, invalid_trophy = 0x8055160a;
  static std::string attr(std::string_view tag, std::string_view name) {
    const auto start = tag.find(std::string(name) + "=\"");
    if (start == tag.npos)
      return {};
    const auto value = start + name.size() + 2, end = tag.find('"', value);
    return end == tag.npos ? std::string{}
                           : std::string(tag.substr(value, end - value));
  }
  static bool integer(std::string_view value, U &result) {
    const auto [p, ec] =
        std::from_chars(value.data(), value.data() + value.size(), result);
    return ec == std::errc{} && p == value.data() + value.size();
  }
  static std::string xml(std::string_view value) {
    std::string out;
    for (char ch : value) {
      if (ch == '&')
        out += "&amp;";
      else if (ch == '<')
        out += "&lt;";
      else if (ch == '>')
        out += "&gt;";
      else if (ch == '"')
        out += "&quot;";
      else
        out += ch;
    }
    return out;
  }
  static bool regular(const std::filesystem::path &path,
                      std::uintmax_t maximum) {
    std::error_code ec;
    return !std::filesystem::is_symlink(path, ec) &&
           std::filesystem::is_regular_file(path, ec) &&
           std::filesystem::file_size(path, ec) <= maximum && !ec;
  }
  std::filesystem::path record(int user) const {
    return store_ / "users" / std::to_string(user) / (npwr_ + ".xml");
  }
  bool load_user(int user) {
    if (users_.contains(user))
      return true;
    const auto *directory = std::getenv("SKY_TROPHY_CATALOGUES");
    const auto *store = std::getenv("SKY_TROPHY_STORE");
    const auto *icons = std::getenv("SKY_TROPHY_ICONS");
    if (!directory || !store || !icons)
      return false;
    catalogues_ = directory;
    store_ = store;
    icons_ = icons;
    const auto file = catalogues_ / (std::to_string(user) + ".tsv");
    if (!regular(file, 2 * 1024 * 1024))
      return false;
    std::ifstream input(file);
    std::string line;
    if (!std::getline(input, line))
      return false;
    std::istringstream header(line);
    std::string magic, npwr, title;
    std::getline(header, magic, '\t');
    std::getline(header, npwr, '\t');
    std::getline(header, title);
    if (magic != "SKYTROPHIES1" || npwr.size() != 12 ||
        npwr.substr(0, 4) != "NPWR" || npwr[9] != '_' ||
        npwr.find_first_not_of("0123456789", 4) < 9 || npwr[10] < '0' ||
        npwr[10] > '9' || npwr[11] < '0' || npwr[11] > '9')
      return false;
    if (!npwr_.empty() && npwr_ != npwr)
      return false;
    npwr_ = npwr;
    title_ = title;
    std::vector<Item> items;
    std::set<int> ids;
    while (std::getline(input, line)) {
      std::istringstream row(line);
      std::array<std::string, 8> columns{};
      for (auto &value : columns)
        std::getline(row, value, '\t');
      std::array<U, 6> numbers{};
      for (unsigned i = 0; i < 6; ++i)
        if (!integer(columns[i], numbers[i]))
          return false;
      if (numbers[0] >= 128 || numbers[1] > 4 || numbers[2] > 127 ||
          numbers[3] > 1 || numbers[4] > 1 ||
          !ids.insert(static_cast<int>(numbers[0])).second ||
          columns[6].size() > 4096 || columns[7].size() > 8192)
        return false;
      items.push_back({static_cast<int>(numbers[0]),
                       static_cast<int>(numbers[1]),
                       static_cast<int>(numbers[2]), numbers[3] != 0,
                       numbers[4] != 0, numbers[5], columns[6], columns[7]});
    }
    if (items.empty() || items.size() > 128)
      return false;
    const auto progress = record(user);
    std::error_code ec;
    if (std::filesystem::exists(progress, ec) ||
        std::filesystem::is_symlink(progress, ec)) {
      if (!regular(progress, 2 * 1024 * 1024))
        return false;
      std::ifstream saved(progress);
      std::string document((std::istreambuf_iterator<char>(saved)), {});
      std::set<int> found;
      if (document.find("<!DOCTYPE") != document.npos ||
          document.find("<!ENTITY") != document.npos)
        return false;
      std::size_t at = 0;
      while ((at = document.find("<trophy ", at)) != document.npos) {
        const auto end = document.find('>', at);
        if (end == document.npos)
          return false;
        const auto tag = std::string_view(document).substr(at, end - at);
        U id = 0, timestamp = 0;
        const auto state = attr(tag, "unlockstate");
        if (!integer(attr(tag, "id"), id) || id >= 128 ||
            !integer(attr(tag, "timestamp"), timestamp) ||
            (state != "true" && state != "false" && state != "1" &&
             state != "0"))
          return false;
        auto item =
            std::find_if(items.begin(), items.end(), [&](const Item &entry) {
              return entry.id == static_cast<int>(id);
            });
        if (item == items.end() || !found.insert(static_cast<int>(id)).second)
          return false;
        item->unlocked = state == "true" || state == "1";
        item->timestamp = timestamp;
        at = end + 1;
      }
      if (found.size() != items.size())
        return false;
    }
    users_.emplace(user, std::move(items));
    return true;
  }
  bool save(int user, const std::vector<Item> &items) {
    namespace fs = std::filesystem;
    const auto destination = record(user);
    std::error_code ec;
    fs::create_directories(destination.parent_path(), ec);
    if (ec ||
        fs::weakly_canonical(destination.parent_path(), ec) !=
            destination.parent_path() ||
        ec || fs::is_symlink(destination, ec))
      return false;
    const auto temporary =
        destination.string() + ".new-" + std::to_string(getpid());
    FILE *file = std::fopen(temporary.c_str(), "wx");
    if (!file)
      return false;
    std::ostringstream document;
    document << "<?xml version=\"1.0\" "
                "encoding=\"utf-8\"?>\n<trophyconf><title-name>"
             << xml(title_) << "</title-name>\n";
    constexpr char grades[]{'?', 'P', 'G', 'S', 'B'};
    for (const auto &item : items)
      document << "<trophy id=\"" << item.id << "\" ttype=\""
               << grades[item.grade] << "\" gid=\"" << item.group
               << "\" hidden=\"" << (item.hidden ? "yes" : "no")
               << "\" unlockstate=\"" << (item.unlocked ? "true" : "false")
               << "\" timestamp=\"" << item.timestamp << "\"><name>"
               << xml(item.name) << "</name><detail>" << xml(item.detail)
               << "</detail></trophy>\n";
    document << "</trophyconf>\n";
    const auto bytes = document.str();
    const bool wrote =
        std::fwrite(bytes.data(), 1, bytes.size(), file) == bytes.size();
    const bool flushed = std::fflush(file) == 0 && fsync(fileno(file)) == 0;
    const bool closed = std::fclose(file) == 0;
    if (!wrote || !flushed || !closed ||
        std::rename(temporary.c_str(), destination.c_str())) {
      std::remove(temporary.c_str());
      return false;
    }
    return true;
  }
  U icon(const std::filesystem::path &file, U buffer, U size_pointer) {
    if (!size_pointer)
      return invalid_argument;
    if (!regular(file, 2 * 1024 * 1024))
      return 0x805516c2;
    const auto needed = std::filesystem::file_size(file);
    auto &size = *reinterpret_cast<U *>(size_pointer);
    if (!buffer) {
      size = needed;
      return 0;
    }
    if (size < needed) {
      size = needed;
      return 0x80551605;
    }
    std::ifstream input(file, std::ios::binary);
    if (!input.read(reinterpret_cast<char *>(buffer),
                    static_cast<std::streamsize>(needed)))
      return 0x805516c2;
    size = needed;
    return 0;
  }
  static void text(char *target, std::size_t size, const std::string &value) {
    std::memset(target, 0, size);
    std::memcpy(target, value.data(), std::min(size - 1, value.size()));
  }

public:
  static bool supports(std::string_view identity) {
    const auto split = identity.find('#');
    return split != identity.npos &&
           identity.substr(split) == "#libSceNpTrophy#libSceNpTrophy" &&
           std::find(nids.begin(), nids.end(), identity.substr(0, split)) !=
               nids.end();
  }
  U call(std::string_view identity, const U *a) {
    if (!supports(identity) || !a)
      return 0x80551622;
    std::lock_guard lock(mutex_);
    const auto nid = identity.substr(0, identity.find('#'));
    const auto operation =
        std::find(nids.begin(), nids.end(), nid) - nids.begin();
    if (operation == 0) {
      if (!a[0] || a[3])
        return invalid_argument;
      if (!LocalPlayers::valid_user(a[1]))
        return 0x8055161c;
      if (a[2])
        return 0x805516c2;
      for (const auto &[id, ctx] : contexts_)
        if (ctx.user == static_cast<int>(a[1]))
          return 0x80551613;
      if (contexts_.size() >= 16)
        return 0x80551623;
      if (!load_user(static_cast<int>(a[1])))
        return 0x80551622;
      const int id = next_context_++;
      contexts_.emplace(id, Context{static_cast<int>(a[1]), false});
      *reinterpret_cast<int *>(a[0]) = id;
      return 0;
    }
    if (operation == 1) {
      if (!a[0])
        return invalid_argument;
      if (handles_.size() >= 16)
        return 0x80551624;
      const int id = next_handle_++;
      handles_.insert(id);
      *reinterpret_cast<int *>(a[0]) = id;
      return 0;
    }
    if (operation == 2)
      return contexts_.erase(static_cast<int>(a[0])) ? 0 : invalid_context;
    if (operation == 3)
      return handles_.erase(static_cast<int>(a[0])) ? 0 : invalid_handle;
    if (operation == 13)
      return handles_.contains(static_cast<int>(a[0])) ? 0 : invalid_handle;
    auto found = contexts_.find(static_cast<int>(a[0]));
    if (found == contexts_.end())
      return invalid_context;
    if (!handles_.contains(static_cast<int>(a[1])))
      return invalid_handle;
    auto &ctx = found->second;
    if (operation == 4) {
      if (a[2])
        return invalid_argument;
      if (ctx.registered)
        return 0x80551610;
      ctx.registered = true;
      return 0;
    }
    if (!ctx.registered)
      return 0x8055160f;
    auto &items = users_.at(ctx.user);
    if (operation == 5) {
      if (!a[3])
        return invalid_argument;
      auto changed = items;
      auto item =
          std::find_if(changed.begin(), changed.end(), [&](const Item &i) {
            return i.id == static_cast<int>(a[2]);
          });
      if (item == changed.end())
        return invalid_trophy;
      if (item->grade == 1)
        return 0x8055160d;
      if (item->unlocked)
        return 0x8055160c;
      const auto timestamp = static_cast<U>(
          std::chrono::duration_cast<std::chrono::seconds>(
              std::chrono::system_clock::now().time_since_epoch())
              .count());
      item->unlocked = true;
      item->timestamp = timestamp;
      int platinum = -1;
      const bool complete =
          std::all_of(changed.begin(), changed.end(), [](const Item &i) {
            return i.group != 0 || i.grade == 1 || i.unlocked;
          });
      if (complete)
        for (auto &i : changed)
          if (i.group == 0 && i.grade == 1 && !i.unlocked) {
            i.unlocked = true;
            i.timestamp = timestamp;
            platinum = i.id;
            break;
          }
      if (!save(ctx.user, changed))
        return 0x80551603;
      items = std::move(changed);
      *reinterpret_cast<int *>(a[3]) = platinum;
      std::printf("{\"event\":\"trophy-unlocked\",\"user\":%d,\"id\":%d,"
                  "\"platinum\":%d}\n",
                  ctx.user, static_cast<int>(a[2]), platinum);
      std::fflush(stdout); // The launcher follows runtime.log live.
      const char *popups = std::getenv("SKY_TROPHY_POPUPS");
      if (skyrender_show_toast && !(popups && popups[0] == '0')) {
        for (const int id : {static_cast<int>(a[2]), platinum})
          for (const auto &i : items)
            if (i.id == id)
              skyrender_show_toast(i.grade == 1 ? "Platinum trophy unlocked"
                                                : "Trophy unlocked",
                                   i.name.c_str(), i.grade);
      }
      return 0;
    }
    if (operation == 12) {
      if (!a[2] || !a[3])
        return invalid_argument;
      auto *flags = reinterpret_cast<std::uint32_t *>(a[2]);
      std::fill_n(flags, 4, 0u);
      for (const auto &i : items)
        if (i.unlocked)
          flags[unsigned(i.id) / 32] |= 1u << (unsigned(i.id) % 32);
      *reinterpret_cast<std::uint32_t *>(a[3]) =
          static_cast<std::uint32_t>(items.size());
      return 0;
    }
    if (operation == 7) {
      const auto item =
          std::find_if(items.begin(), items.end(), [&](const Item &i) {
            return i.id == static_cast<int>(a[2]);
          });
      if (item == items.end())
        return invalid_trophy;
      if (a[3]) {
        auto *d = reinterpret_cast<TrophyDetails *>(a[3]);
        if (d->size != sizeof(*d))
          return invalid_argument;
        const U size = d->size;
        *d = {};
        d->size = size;
        d->id = item->id;
        d->grade = item->grade;
        d->group = item->group;
        d->hidden = item->hidden;
        text(d->name, sizeof(d->name), item->name);
        text(d->description, sizeof(d->description), item->detail);
      }
      if (a[4]) {
        auto *d = reinterpret_cast<TrophyData *>(a[4]);
        if (d->size != sizeof(*d))
          return invalid_argument;
        *d = {sizeof(*d), item->id, item->unlocked, {}, item->timestamp};
      }
      return a[3] || a[4] ? 0 : invalid_argument;
    }
    if (operation == 8)
      return icon(icons_ / "ICON0.PNG", a[2], a[3]);
    if (operation == 9) {
      if (std::none_of(items.begin(), items.end(), [&](const Item &i) {
            return i.id == static_cast<int>(a[2]);
          }))
        return invalid_trophy;
      char name[32];
      std::snprintf(name, sizeof(name), "TROP%03d.PNG", static_cast<int>(a[2]));
      return icon(icons_ / name, a[3], a[4]);
    }
    if (operation == 10) {
      if (a[2] != 0 && static_cast<int>(a[2]) != -1)
        return 0x8055160b;
      return icon(icons_ / "GR000.PNG", a[3], a[4]);
    }
    if (operation == 6 || operation == 11) {
      const bool group = operation == 11;
      if (group && a[2] != 0 && static_cast<int>(a[2]) != -1)
        return 0x8055160b;
      const unsigned arg = group ? 3 : 2;
      std::array<std::uint32_t, 5> total{}, earned{};
      for (const auto &i : items) {
        if (group && i.group != 0)
          continue;
        ++total[0];
        if (i.grade)
          ++total[static_cast<unsigned>(i.grade)];
        if (i.unlocked) {
          ++earned[0];
          if (i.grade)
            ++earned[static_cast<unsigned>(i.grade)];
        }
      }
      const auto percent = total[0] ? earned[0] * 100 / total[0] : 0;
      if (a[arg]) {
        if (group) {
          auto *d = reinterpret_cast<GroupDetails *>(a[arg]);
          if (d->size != sizeof(*d))
            return invalid_argument;
          *d = {};
          d->size = sizeof(*d);
          d->group = static_cast<int>(a[2]);
          d->total = total[0];
          d->platinum = total[1];
          d->gold = total[2];
          d->silver = total[3];
          d->bronze = total[4];
          text(d->name, sizeof(d->name), title_);
        } else {
          auto *d = reinterpret_cast<GameDetails *>(a[arg]);
          if (d->size != sizeof(*d))
            return invalid_argument;
          *d = {};
          d->size = sizeof(*d);
          d->groups = 1;
          d->total = total[0];
          d->platinum = total[1];
          d->gold = total[2];
          d->silver = total[3];
          d->bronze = total[4];
          text(d->name, sizeof(d->name), title_);
        }
      }
      if (a[arg + 1]) {
        if (group) {
          auto *d = reinterpret_cast<GroupData *>(a[arg + 1]);
          if (d->size != sizeof(*d))
            return invalid_argument;
          *d = {sizeof(*d), static_cast<int>(a[2]),
                earned[0],  earned[1],
                earned[2],  earned[3],
                earned[4],  percent,
                {}};
        } else {
          auto *d = reinterpret_cast<GameData *>(a[arg + 1]);
          if (d->size != sizeof(*d))
            return invalid_argument;
          *d = {sizeof(*d), earned[0], earned[1], earned[2],
                earned[3],  earned[4], percent};
        }
      }
      return a[arg] || a[arg + 1] ? 0 : invalid_argument;
    }
    return 0x80551622;
  }
};
