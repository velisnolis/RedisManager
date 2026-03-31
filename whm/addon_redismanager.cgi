#!/usr/local/cpanel/3rdparty/bin/perl
#WHMADDON:addon_redismanager:Redis Manager:redismanager-icon.png
#ACLS:all
# RedisManager WHM Plugin — Admin Interface
# Installs to: /usr/local/cpanel/whostmgr/docroot/cgi/addon_redismanager.cgi

use strict;
use warnings;

BEGIN {
    unshift @INC, '/usr/local/cpanel';
}

use Whostmgr::ACLS          ();
use Whostmgr::HTMLInterface ();
use CGI;
use JSON::PP;

my $CTL       = '/opt/redismanager/bin/redismanager-ctl';
my $STATE     = '/var/lib/redismanager/state.json';
my $CONF_FILE = '/opt/redismanager/etc/redismanager.conf';
my $VERSION   = '0.3.0';

# --- WHM Auth ---
Whostmgr::ACLS::init_acls();
if (!Whostmgr::ACLS::hasroot()) {
    print "Content-Type: text/html\r\n\r\n";
    print "Access denied.\n";
    exit;
}

# --- Parse form (single CGI instance — reused everywhere) ---
my $cgi = CGI->new;
my $action      = $cgi->param('action')      // '';
my $username    = $cgi->param('username')    // '';
my $memory      = $cgi->param('memory')      // '';
my $maxclients  = $cgi->param('maxclients')  // '';

# --- Handle POST actions ---
my $message  = '';
my $msg_type = '';

if ($ENV{'REQUEST_METHOD'} eq 'POST' && $action) {
    ($message, $msg_type) = handle_action($cgi, $action, $username, $memory, $maxclients);
}

# --- Get data ---
my @accounts  = get_cpanel_accounts();
my %state     = get_state();
my %info      = get_info();
my %conf      = get_conf();
my @binaries  = get_binary_candidates();

# --- WHM header ---
print "Content-Type: text/html\r\n\r\n";
Whostmgr::HTMLInterface::defheader("Redis Manager v${VERSION}", '/addon_plugins/redismanager-icon.svg', '/cgi/addon_redismanager.cgi');

# --- Page content ---
print_page(\@accounts, \%state, \%info, \%conf, \@binaries, $message, $msg_type);

# --- WHM footer ---
Whostmgr::HTMLInterface::sendfooter();

exit;

# =========================================================================
# Functions
# =========================================================================

# Simple HTML entity escaping for output safety.
# WHM is root-only so XSS risk is minimal, but it's good practice to escape
# any data that could theoretically contain HTML characters (error messages,
# domain names from whmapi, etc.).
sub html_escape {
    my ($str) = @_;
    return '' unless defined $str;
    $str =~ s/&/&amp;/g;
    $str =~ s/</&lt;/g;
    $str =~ s/>/&gt;/g;
    $str =~ s/"/&quot;/g;
    return $str;
}

sub handle_action {
    my ($cgi_obj, $act, $user, $mem, $mc) = @_;

    # Global config save — no user needed, params read from the shared $cgi_obj
    if ($act eq 'save-config') {
        return save_global_config($cgi_obj);
    }

    return ('', '') unless $user && $user =~ /^[a-z][a-z0-9_]{0,30}$/;

    my $output;
    if ($act eq 'enable') {
        $mem = 64 unless $mem && $mem =~ /^\d+$/ && $mem >= 16 && $mem <= 512;
        $output = `$CTL enable '$user' '$mem' 2>&1`;
    } elsif ($act eq 'disable') {
        $output = `$CTL disable '$user' 2>&1`;
    } elsif ($act eq 'restart') {
        $output = `$CTL restart '$user' 2>&1`;
    } elsif ($act eq 'flush') {
        $output = `$CTL flush '$user' 2>&1`;
    } elsif ($act eq 'set-memory') {
        return ('Invalid memory value (16-512)', 'error') unless $mem && $mem =~ /^\d+$/ && $mem >= 16 && $mem <= 512;
        $output = `$CTL set-memory '$user' '$mem' 2>&1`;
    } elsif ($act eq 'set-maxclients') {
        return ('Invalid maxclients value (8-1024)', 'error') unless $mc && $mc =~ /^\d+$/ && $mc >= 8 && $mc <= 1024;
        $output = `$CTL set-maxclients '$user' '$mc' 2>&1`;
    } else {
        return ('Unknown action', 'error');
    }

    my $rc = $? >> 8;
    if ($rc == 0) {
        return ("OK: $act for $user", 'success');
    } else {
        chomp $output;
        return ("Error: " . html_escape($output), 'error');
    }
}

sub save_global_config {
    my ($cgi_obj) = @_;
    my %existing_conf = get_conf();

    # Read params from the SAME CGI instance (POST body is already consumed)
    my $new_mem = $cgi_obj->param('cfg_default_memory')     // '';
    my $new_mc  = $cgi_obj->param('cfg_default_maxclients')  // '';
    my $new_bud = $cgi_obj->param('cfg_total_budget')        // '';
    my $new_bin = $cgi_obj->param('cfg_redis_binary')        // '';

    # Validate
    if ($new_mem && !($new_mem =~ /^\d+$/ && $new_mem >= 16 && $new_mem <= 1024)) {
        return ('Invalid default memory (16-1024)', 'error');
    }
    if ($new_mc && !($new_mc =~ /^\d+$/ && $new_mc >= 8 && $new_mc <= 4096)) {
        return ('Invalid default maxclients (8-4096)', 'error');
    }
    if ($new_bud && !($new_bud =~ /^\d+$/ && $new_bud >= 64 && $new_bud <= 65536)) {
        return ('Invalid total budget (64-65536)', 'error');
    }
    if ($new_bin && !($new_bin =~ m{^/[A-Za-z0-9_./+-]+$})) {
        return ('Invalid Redis binary path', 'error');
    }

    # Read current config
    open my $fh, '<', $CONF_FILE or return ("Cannot read config: $!", 'error');
    my @lines = <$fh>;
    close $fh;

    # Replace values
    for my $line (@lines) {
        if ($new_mem && $line =~ /^DEFAULT_MEMORY_MB=/) {
            $line = "DEFAULT_MEMORY_MB=$new_mem\n";
        }
        if ($new_mc && $line =~ /^DEFAULT_MAXCLIENTS=/) {
            $line = "DEFAULT_MAXCLIENTS=$new_mc\n";
        }
        if ($new_bud && $line =~ /^TOTAL_BUDGET_MB=/) {
            $line = "TOTAL_BUDGET_MB=$new_bud\n";
        }
    }

    open my $wfh, '>', $CONF_FILE or return ("Cannot write config: $!", 'error');
    print $wfh @lines;
    close $wfh;

    if ($new_bin && ($existing_conf{REDIS_BINARY} // '') ne $new_bin) {
        my $output = `$CTL apply-binary '$new_bin' 2>&1`;
        my $rc = $? >> 8;
        if ($rc != 0) {
            chomp $output;
            return ("Config saved, but failed to apply binary: " . html_escape($output), 'error');
        }
    }

    return ('Global configuration saved', 'success');
}

sub get_cpanel_accounts {
    my @accounts;
    my $json = `whmapi1 listaccts --output=json 2>/dev/null`;
    if ($json) {
        eval {
            my $data = decode_json($json);
            if ($data->{data} && $data->{data}{acct}) {
                for my $acct (@{$data->{data}{acct}}) {
                    push @accounts, {
                        user      => $acct->{user},
                        domain    => $acct->{domain},
                        plan      => $acct->{plan},
                        suspended => ($acct->{suspended} ? 1 : 0),
                    };
                }
            }
        };
    }
    return sort { $a->{user} cmp $b->{user} } @accounts;
}

sub get_state {
    my %state;
    if (-f $STATE) {
        if (open my $fh, '<', $STATE) {
            local $/;
            my $json = <$fh>;
            close $fh;
            eval {
                my $data = decode_json($json);
                %state = %$data if ref $data eq 'HASH';
            };
        }
    }
    return %state;
}

sub get_info {
    my %info;
    my $output = `$CTL info 2>/dev/null`;
    for my $line (split /\n/, $output // '') {
        if ($line =~ /^(\w[\w\s]+?):\s+(.+)/) {
            my ($k, $v) = ($1, $2);
            $k =~ s/\s+/_/g;
            $info{lc $k} = $v;
        }
    }
    return %info;
}

sub get_conf {
    my %conf;
    if (open my $fh, '<', $CONF_FILE) {
        while (<$fh>) {
            chomp;
            next if /^\s*#/ || /^\s*$/;
            if (/^(\w+)=(.*)/) {
                my ($k, $v) = ($1, $2);
                $v =~ s/^"(.*)"$/$1/;
                $conf{$k} = $v;
            }
        }
        close $fh;
    }
    return %conf;
}

sub get_binary_candidates {
    my @binaries;
    my $output = `$CTL list-binaries 2>/dev/null`;
    for my $line (split /\n/, $output // '') {
        next unless $line;
        my ($path, $version, $cli) = split /\t/, $line, 3;
        next unless $path;
        push @binaries, {
            path    => $path,
            version => ($version // ''),
            cli     => ($cli // ''),
        };
    }
    return @binaries;
}

sub binary_friendly_name {
    my ($path, $version) = @_;
    my $name = 'Custom binary';

    if (($path // '') =~ m{/opt/alt/valkey/bin/valkey-server$}) {
        $name = 'CloudLinux Valkey';
    } elsif (($path // '') =~ m{/opt/alt/redis/bin/redis-server$}) {
        $name = 'CloudLinux Redis';
    } elsif (($path // '') =~ m{/valkey-server$}) {
        $name = 'Valkey';
    } elsif (($path // '') =~ m{/redis-server$}) {
        $name = 'Redis';
    }

    if (($version // '') =~ /v=([0-9][^ ]*)/) {
        $name .= " $1";
    }

    return $name;
}

sub is_service_active {
    my ($user) = @_;
    system("systemctl is-active --quiet 'redis-managed\@${user}' 2>/dev/null");
    return $? == 0;
}

sub print_page {
    my ($accounts, $state, $info, $conf, $binaries, $msg, $msg_type) = @_;

    my $total_mem  = 0;
    my $total_inst = 0;
    for my $v (values %$state) {
        $total_mem += ($v->{memory_mb} // 64);
        $total_inst++;
    }
    my $budget_mb = $conf->{TOTAL_BUDGET_MB} // 2048;
    my $budget = "${total_mem}MB / ${budget_mb}MB";

    my $security_token = $ENV{'cp_security_token'} || '';
    my $form_action = "${security_token}/cgi/addon_redismanager.cgi";

    my $binary  = html_escape($info->{binary}  // $conf->{REDIS_BINARY} // '/opt/alt/redis/bin/redis-server');
    my $version = html_escape($info->{version} // 'N/A');

    my $default_mem = $conf->{DEFAULT_MEMORY_MB} // 64;
    my $default_mc  = $conf->{DEFAULT_MAXCLIENTS} // 128;
    my $current_binary = $conf->{REDIS_BINARY} // '/opt/alt/redis/bin/redis-server';

    # CSS
    print <<HTML;
<style>
    .rm-stats { display: flex; gap: 40px; margin-bottom: 15px; }
    .rm-stats .stats { text-align: center; min-width: 120px; }
    .rm-stats .stats b { display: block; font-size: 1.1em; }
    .rm-input-sm { width: 60px; padding: 2px 4px; text-align: center; border: 1px solid #bbb; border-radius: 3px; }
    .rm-socket { font-family: monospace; font-size: 0.85em; color: #555; }
    td form { display: inline; margin: 0; }
    .label-success { background-color: #5cb85c; }
    .label-danger  { background-color: #d9534f; }
    .label-default { background-color: #999; }
    .label-warning { background-color: #f0ad4e; color: #333; }

    /* Expandable row (List Accounts pattern) */
    .rm-toggle { cursor: pointer; width: 20px; text-align: center; font-family: monospace; font-weight: bold; color: #3276b1; user-select: none; }
    .rm-toggle:hover { color: #285e8e; }
    .rm-detail-row td { padding: 0 !important; }
    .rm-detail-panel { padding: 12px 20px 15px 36px; border-bottom: 2px solid #d9dee4; }
    .rm-detail-panel .rm-section { margin-bottom: 12px; }
    .rm-detail-panel .rm-section:last-child { margin-bottom: 0; }
    .rm-detail-panel h4 { margin: 0 0 6px; font-size: 13px; color: #555; text-transform: uppercase; letter-spacing: 0.5px; }
    .rm-detail-panel .rm-info-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 4px 20px; font-size: 13px; }
    .rm-detail-panel .rm-info-grid .rm-label { color: #888; }
    .rm-detail-panel .rm-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }

    /* Global config panel */
    .rm-config-panel { background: #f5f7fa; border: 1px solid #d9dee4; border-radius: 4px; padding: 15px 20px; margin-bottom: 20px; }
    .rm-config-panel h3 { margin: 0 0 12px; font-size: 14px; }
    .rm-config-grid { display: flex; flex-wrap: wrap; gap: 15px; align-items: flex-start; }
    .rm-config-field { display: flex; flex-direction: column; gap: 3px; justify-content: flex-start; }
    .rm-config-field-small { min-width: 120px; }
    .rm-config-field-binary { flex: 0 1 420px; min-width: 220px; }
    .rm-config-field-details { flex: 0 1 auto; min-width: 280px; max-width: 100%; }
    .rm-config-field-action { margin-left: auto; justify-content: flex-start; }
    .rm-config-field label { font-size: 12px; color: #666; }
    .rm-config-field input { width: 80px; padding: 4px 6px; border: 1px solid #bbb; border-radius: 3px; text-align: center; }
    .rm-config-field select { width: 100%; min-width: 220px; max-width: 100%; padding: 4px 6px; border: 1px solid #bbb; border-radius: 3px; }
    .rm-config-help { min-height: 64px; padding: 8px 10px; border: 1px solid #d9dee4; border-radius: 4px; background: #fff; font-size: 12px; line-height: 1.45; color: #555; }
    .rm-config-help code { font-size: 11px; background: #eef3f8; padding: 1px 4px; border-radius: 3px; }
    .rm-config-help .rm-help-title { display: block; font-weight: 600; color: #333; margin-bottom: 3px; }
</style>
<script>
function rmToggle(user) {
    var row = document.getElementById('detail-' + user);
    var icon = document.getElementById('toggle-' + user);
    if (row.style.display === 'none' || row.style.display === '') {
        row.style.display = 'table-row';
        icon.textContent = '\\u2212';
    } else {
        row.style.display = 'none';
        icon.textContent = '+';
    }
}
function rmConfirm(action, user) {
    if (action === 'disable') return confirm('Disable Redis for ' + user + '? This will delete all cached data.');
    if (action === 'flush') return confirm('Flush all Redis data for ' + user + '?');
    return true;
}
function rmUpdateBinaryDetails() {
    var select = document.getElementById('cfg_redis_binary');
    var panel = document.getElementById('rm-binary-details');
    if (!select || !panel) return;
    var option = select.options[select.selectedIndex];
    if (!option) return;
    var title = option.getAttribute('data-friendly') || option.textContent;
    var version = option.getAttribute('data-version') || 'Unknown version';
    var path = option.value || '';
    var cli = option.getAttribute('data-cli') || 'Not detected';
    panel.innerHTML =
        '<span class="rm-help-title">' + title + '</span>' +
        'Version: <code>' + version + '</code><br>' +
        'Server path: <code>' + path + '</code><br>' +
        'CLI path: <code>' + cli + '</code>';
}
</script>

<div class="body-content">
HTML

    # Message banner (escaped)
    if ($msg) {
        my $escaped_msg = html_escape($msg);
        if ($msg_type eq 'success') {
            print qq{<div style="padding:12px 16px;margin-bottom:15px;border-left:4px solid #3c763d;background:#dff0d8;color:#3c763d;font-size:14px;border-radius:3px"><strong>&#10004;</strong> $escaped_msg</div>\n};
        } else {
            print qq{<div style="padding:12px 16px;margin-bottom:15px;border-left:4px solid #a94442;background:#f2dede;color:#a94442;font-size:14px;border-radius:3px"><strong>&#10008;</strong> $escaped_msg</div>\n};
        }
    }

    # Stats
    print <<HTML;
<div class="rm-stats">
    <div class="stats"><b>${total_inst}</b> Instances</div>
    <div class="stats"><b>${budget}</b> Memory budget</div>
    <div class="stats"><b>${version}</b> Redis version</div>
    <div class="stats"><b style="font-size:0.85em">${binary}</b> Binary</div>
</div>
HTML

    # Global config panel
    my %seen_binary = map { $_->{path} => 1 } @$binaries;
    my @binary_options = @$binaries;
    if (!$seen_binary{$current_binary}) {
        unshift @binary_options, {
            path    => $current_binary,
            version => 'current (not auto-detected)',
            cli     => '',
        };
    }

    my $binary_select = qq{<select name="cfg_redis_binary" id="cfg_redis_binary" onchange="rmUpdateBinaryDetails()">};
    for my $bin (@binary_options) {
        my $path = html_escape($bin->{path});
        my $version = html_escape($bin->{version} // '');
        my $cli = html_escape($bin->{cli} // '');
        my $friendly = html_escape(binary_friendly_name($bin->{path}, $bin->{version}));
        my $selected = ($bin->{path} // '') eq $current_binary ? ' selected' : '';
        $binary_select .= qq{<option value="$path" data-friendly="$friendly" data-version="$version" data-cli="$cli"$selected>$friendly</option>};
    }
    $binary_select .= qq{</select>};

    print <<HTML;
<div class="rm-config-panel">
    <h3>Global Configuration</h3>
    <form method="post" action="$form_action">
        <input type="hidden" name="action" value="save-config">
        <div class="rm-config-grid">
            <div class="rm-config-field rm-config-field-small">
                <label>Default memory (MB)</label>
                <input type="number" name="cfg_default_memory" value="$default_mem" min="16" max="1024">
            </div>
            <div class="rm-config-field rm-config-field-small">
                <label>Default maxclients</label>
                <input type="number" name="cfg_default_maxclients" value="$default_mc" min="8" max="4096">
            </div>
            <div class="rm-config-field rm-config-field-small">
                <label>Total budget (MB)</label>
                <input type="number" name="cfg_total_budget" value="$budget_mb" min="64" max="65536">
            </div>
            <div class="rm-config-field rm-config-field-binary">
                <label>Redis / Valkey binary</label>
                $binary_select
            </div>
            <div class="rm-config-field rm-config-field-details">
                <label>Selected binary</label>
                <div id="rm-binary-details" class="rm-config-help"></div>
            </div>
            <div class="rm-config-field rm-config-field-action">
                <label>&nbsp;</label>
                <button type="submit" class="btn btn-primary btn-sm">Save</button>
            </div>
        </div>
    </form>
</div>
HTML

    # Main table — compact with expandable rows
    print <<HTML;
<div class="yui-skin-sam">
<table class="sortable" width="100%" cellpadding="0" cellspacing="0" border="0">
<thead>
<tr class="tblheader0">
    <th width="20"></th>
    <th>Domain</th>
    <th>User</th>
    <th style="text-align:center">Plan</th>
    <th style="text-align:center">Redis</th>
    <th style="text-align:center">Memory</th>
    <th style="text-align:center">Maxclients</th>
    <th style="text-align:center">Actions</th>
</tr>
</thead>
<tbody>
HTML

    my $row = 0;
    for my $acct (@$accounts) {
        my $user = $acct->{user};
        my $domain = html_escape($acct->{domain});
        my $plan   = html_escape($acct->{plan});
        my $is_managed = exists $state->{$user};
        my $mem_mb = $is_managed ? ($state->{$user}{memory_mb} // 64) : $default_mem;
        my $mc_val = $is_managed ? ($state->{$user}{maxclients} // $default_mc) : $default_mc;
        my $is_active = $is_managed ? is_service_active($user) : 0;

        my $shade = ($row % 2) ? 'tdshade1' : 'tdshade2';
        $row++;

        # Status badge
        my $status_badge;
        if ($acct->{suspended}) {
            $status_badge = '<span class="label label-warning">suspended</span>';
        } elsif ($is_managed && $is_active) {
            $status_badge = '<span class="label label-success">active</span>';
        } elsif ($is_managed) {
            $status_badge = '<span class="label label-danger">inactive</span>';
        } else {
            $status_badge = '<span class="label label-default">off</span>';
        }

        # Quick action (enable or nothing in compact row)
        my $quick_action = '';
        if (!$is_managed && !$acct->{suspended}) {
            $quick_action = qq{
                <form method="post" action="$form_action">
                    <input type="hidden" name="action" value="enable">
                    <input type="hidden" name="username" value="$user">
                    <input type="hidden" name="memory" value="$default_mem">
                    <button type="submit" class="btn btn-primary btn-sm">Enable</button>
                </form>
            };
        }

        # Toggle icon — only for managed accounts
        my $toggle_td = '';
        if ($is_managed) {
            $toggle_td = qq{<td class="$shade rm-toggle" id="toggle-$user" onclick="rmToggle('$user')">+</td>};
        } else {
            $toggle_td = qq{<td class="$shade"></td>};
        }

        print qq{$toggle_td};
        print qq{<td class="$shade"><b>$domain</b></td>};
        print qq{<td class="$shade">$user</td>};
        print qq{<td class="$shade" style="text-align:center">$plan</td>};
        print qq{<td class="$shade" style="text-align:center">$status_badge</td>};
        print qq{<td class="$shade" style="text-align:center">@{[$is_managed ? "${mem_mb}MB" : '-']}</td>};
        print qq{<td class="$shade" style="text-align:center">@{[$is_managed ? $mc_val : '-']}</td>};
        print qq{<td class="$shade" style="text-align:center">$quick_action</td>};
        print qq{</tr>\n};

        # Expandable detail row (only for managed accounts)
        if ($is_managed) {
            my $socket = "/home/$user/.redis-managed/redis.sock";
            my $enabled_at = html_escape($state->{$user}{enabled_at} // 'unknown');

            print qq{<tr id="detail-$user" class="rm-detail-row" style="display:none"><td colspan="8" class="tdshade2">};
            print qq{<div class="rm-detail-panel">};

            # Info section
            print qq{<div class="rm-section"><h4>Connection</h4>};
            print qq{<div class="rm-info-grid">};
            print qq{<div><span class="rm-label">Socket:</span> <span class="rm-socket">$socket</span></div>};
            print qq{<div><span class="rm-label">Enabled:</span> $enabled_at</div>};
            print qq{</div>};
            print qq{</div>};

            # Joomla config section
            print qq{<div class="rm-section"><h4>Joomla Configuration</h4>};
            print qq{<div class="rm-info-grid">};
            print qq{<div><span class="rm-label">Cache:</span> Handler=Redis, Host=$socket, Port=6379, DB=0</div>};
            print qq{<div><span class="rm-label">Sessions:</span> Handler=Redis, Host=$socket, Port=6379, DB=1</div>};
            print qq{</div>};
            print qq{</div>};

            # Actions section
            print qq{<div class="rm-section"><h4>Actions</h4>};
            print qq{<div class="rm-actions">};

            # Set memory
            print qq{<form method="post" action="$form_action">};
            print qq{<input type="hidden" name="action" value="set-memory"><input type="hidden" name="username" value="$user">};
            print qq{<input type="number" name="memory" value="$mem_mb" class="rm-input-sm" min="16" max="512">MB };
            print qq{<button type="submit" class="btn btn-default btn-sm">Set memory</button>};
            print qq{</form>};

            # Set maxclients
            print qq{<form method="post" action="$form_action">};
            print qq{<input type="hidden" name="action" value="set-maxclients"><input type="hidden" name="username" value="$user">};
            print qq{<input type="number" name="maxclients" value="$mc_val" class="rm-input-sm" min="8" max="1024"> };
            print qq{<button type="submit" class="btn btn-default btn-sm">Set maxclients</button>};
            print qq{</form>};

            # Restart
            print qq{<form method="post" action="$form_action" onsubmit="return rmConfirm('restart','$user')">};
            print qq{<input type="hidden" name="action" value="restart"><input type="hidden" name="username" value="$user">};
            print qq{<button type="submit" class="btn btn-default btn-sm">Restart</button>};
            print qq{</form>};

            # Flush
            print qq{<form method="post" action="$form_action" onsubmit="return rmConfirm('flush','$user')">};
            print qq{<input type="hidden" name="action" value="flush"><input type="hidden" name="username" value="$user">};
            print qq{<button type="submit" class="btn btn-default btn-sm">Flush</button>};
            print qq{</form>};

            # Disable
            print qq{<form method="post" action="$form_action" onsubmit="return rmConfirm('disable','$user')">};
            print qq{<input type="hidden" name="action" value="disable"><input type="hidden" name="username" value="$user">};
            print qq{<button type="submit" class="btn btn-default btn-sm" style="color:#c9302c">Disable</button>};
            print qq{</form>};

            print qq{</div>};  # rm-actions
            print qq{</div>};  # rm-section

            print qq{</div>};  # rm-detail-panel
            print qq{</td></tr>\n};
        }
    }

    print <<HTML;
</tbody>
</table>
</div>

</div>
HTML

    print qq{<script>rmUpdateBinaryDetails();</script>\n};
}
