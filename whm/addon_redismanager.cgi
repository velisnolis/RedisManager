#!/usr/local/cpanel/3rdparty/bin/perl
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

my $CTL     = '/opt/redismanager/bin/redismanager-ctl';
my $STATE   = '/var/lib/redismanager/state.json';
my $VERSION = '0.1.0';

# --- WHM Auth ---
Whostmgr::ACLS::init_acls();
if (!Whostmgr::ACLS::hasroot()) {
    print "Content-Type: text/html\r\n\r\n";
    print "Access denied.\n";
    exit;
}

# --- Parse form ---
my $cgi = CGI->new;
my $action   = $cgi->param('action')   // '';
my $username = $cgi->param('username') // '';
my $memory   = $cgi->param('memory')   // '';

# --- Handle POST actions ---
my $message  = '';
my $msg_type = '';

if ($ENV{'REQUEST_METHOD'} eq 'POST' && $action) {
    ($message, $msg_type) = handle_action($action, $username, $memory);
}

# --- Get data ---
my @accounts  = get_cpanel_accounts();
my %state     = get_state();
my %info      = get_info();

# --- WHM header ---
print "Content-Type: text/html\r\n\r\n";
Whostmgr::HTMLInterface::defheader("Redis Manager v${VERSION}", '/addon_plugins/redismanager-icon.svg', '/cgi/addon_redismanager.cgi');

# --- Page content ---
print_page(\@accounts, \%state, \%info, $message, $msg_type);

# --- WHM footer ---
Whostmgr::HTMLInterface::sendfooter();

exit;

# =========================================================================
# Functions
# =========================================================================

sub handle_action {
    my ($act, $user, $mem) = @_;
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
        return ('Invalid memory value', 'error') unless $mem && $mem =~ /^\d+$/ && $mem >= 16 && $mem <= 512;
        $output = `$CTL set-memory '$user' '$mem' 2>&1`;
    } else {
        return ('Unknown action', 'error');
    }

    my $rc = $? >> 8;
    if ($rc == 0) {
        return ("OK: $act for $user", 'success');
    } else {
        chomp $output;
        return ("Error: $output", 'error');
    }
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
                        user     => $acct->{user},
                        domain   => $acct->{domain},
                        plan     => $acct->{plan},
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

sub is_service_active {
    my ($user) = @_;
    system("systemctl is-active --quiet 'redis-managed\@${user}' 2>/dev/null");
    return $? == 0;
}

sub print_page {
    my ($accounts, $state, $info, $msg, $msg_type) = @_;

    my $total_mem  = 0;
    my $total_inst = 0;
    for my $v (values %$state) {
        $total_mem += ($v->{memory_mb} // 64);
        $total_inst++;
    }
    my $budget = "${total_mem}MB / 2048MB";

    my $security_token = $ENV{'cp_security_token'} || '';
    my $form_action = "${security_token}/cgi/addon_redismanager.cgi";

    my $binary  = $info->{binary}  // '/opt/alt/redis/bin/redis-server';
    my $version = $info->{version} // 'N/A';

    # Minimal custom CSS — everything else comes from WHM's style_v2_optimized.css
    print <<HTML;
<style>
    .rm-stats { display: flex; gap: 40px; margin-bottom: 15px; }
    .rm-stats .stats { text-align: center; min-width: 120px; }
    .rm-stats .stats b { display: block; font-size: 1.1em; }
    .rm-mem-input { width: 50px; padding: 2px 4px; text-align: center; border: 1px solid #bbb; border-radius: 3px; }
    .rm-socket { font-family: monospace; font-size: 0.85em; color: #555; }
    .rm-joomla-cfg { display: none; background: #f5f7fa; padding: 8px 10px; border: 1px solid #d9dee4; border-radius: 3px; margin-top: 5px; font-size: 0.85em; font-family: monospace; line-height: 1.6; }
    .rm-toggle-cfg { cursor: pointer; color: #3276b1; font-size: 0.85em; }
    .rm-toggle-cfg:hover { text-decoration: underline; }
    td form { display: inline; margin: 0; }
    .label-success { background-color: #5cb85c; }
    .label-danger  { background-color: #d9534f; }
    .label-default { background-color: #999; }
    .label-warning { background-color: #f0ad4e; color: #333; }
</style>
<script>
function rmToggleCfg(user) {
    var el = document.getElementById('cfg-' + user);
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
function rmConfirm(action, user) {
    if (action === 'disable') return confirm('Disable Redis for ' + user + '? This will delete all cached data.');
    if (action === 'flush') return confirm('Flush all Redis data for ' + user + '?');
    return true;
}
</script>

<div class="body-content">

<div class="rm-stats">
    <div class="stats"><b>${total_inst}</b> Instances</div>
    <div class="stats"><b>${budget}</b> Memory budget</div>
    <div class="stats"><b>${version}</b> Redis version</div>
    <div class="stats"><b style="font-size:0.85em">${binary}</b> Binary</div>
</div>
HTML

    # Message banner
    if ($msg) {
        if ($msg_type eq 'success') {
            print qq{<div class="callout callout-success" style="padding:12px 16px;margin-bottom:15px;border-left:4px solid #3c763d;background:#dff0d8;color:#3c763d;font-size:14px;border-radius:3px"><strong>&#10004;</strong> $msg</div>\n};
        } else {
            print qq{<div class="callout callout-danger" style="padding:12px 16px;margin-bottom:15px;border-left:4px solid #a94442;background:#f2dede;color:#a94442;font-size:14px;border-radius:3px"><strong>&#10008;</strong> $msg</div>\n};
        }
    }

    # Table using native WHM classes
    print <<HTML;
<div class="yui-skin-sam">
<table class="sortable" width="100%" cellpadding="0" cellspacing="0" border="0">
<thead>
<tr class="tblheader0">
    <th>User</th>
    <th>Domain</th>
    <th style="text-align:center">Plan</th>
    <th style="text-align:center">Redis</th>
    <th style="text-align:center">Memory</th>
    <th>Socket</th>
    <th style="text-align:center">Actions</th>
</tr>
</thead>
<tbody>
HTML

    my $row = 0;
    for my $acct (@$accounts) {
        my $user = $acct->{user};
        my $is_managed = exists $state->{$user};
        my $mem_mb = $is_managed ? ($state->{$user}{memory_mb} // 64) : 64;
        my $is_active = $is_managed ? is_service_active($user) : 0;

        my $shade = ($row % 2) ? 'tdshade1' : 'tdshade2';
        my $suspended_class = $acct->{suspended} ? ' suspended' : '';
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

        # Socket column
        my $socket_col = '';
        if ($is_managed) {
            my $socket = "/home/$user/.redis-managed/redis.sock";
            $socket_col = qq{<span class="rm-socket">$socket</span><br>};
            $socket_col .= qq{<span class="rm-toggle-cfg" onclick="rmToggleCfg('$user')">Show Joomla config</span>};
            $socket_col .= qq{<div class="rm-joomla-cfg" id="cfg-$user">};
            $socket_col .= qq{<b>Cache:</b> Handler=Redis &middot; Host=$socket &middot; Port=6379 &middot; DB=0<br>};
            $socket_col .= qq{<b>Sessions:</b> Handler=Redis &middot; Host=$socket &middot; Port=6379 &middot; DB=1};
            $socket_col .= qq{</div>};
        }

        # Actions column
        my $actions_col = '';
        if (!$is_managed && !$acct->{suspended}) {
            $actions_col = qq{
                <form method="post" action="$form_action" onsubmit="return rmConfirm('enable','$user')">
                    <input type="hidden" name="action" value="enable">
                    <input type="hidden" name="username" value="$user">
                    <input type="text" name="memory" value="$mem_mb" class="rm-mem-input" title="Memory (MB)">MB
                    <button type="submit" class="btn btn-primary btn-sm">Enable</button>
                </form>
            };
        } elsif ($is_managed) {
            $actions_col = qq{
                <form method="post" action="$form_action" onsubmit="return rmConfirm('restart','$user')">
                    <input type="hidden" name="action" value="restart"><input type="hidden" name="username" value="$user">
                    <button type="submit" class="btn btn-default btn-sm">Restart</button>
                </form>
                <form method="post" action="$form_action" onsubmit="return rmConfirm('flush','$user')">
                    <input type="hidden" name="action" value="flush"><input type="hidden" name="username" value="$user">
                    <button type="submit" class="btn btn-default btn-sm">Flush</button>
                </form>
                <form method="post" action="$form_action" onsubmit="return rmConfirm('disable','$user')">
                    <input type="hidden" name="action" value="disable"><input type="hidden" name="username" value="$user">
                    <button type="submit" class="btn btn-default btn-sm" style="color:#c9302c">Disable</button>
                </form>
                <form method="post" action="$form_action">
                    <input type="hidden" name="action" value="set-memory"><input type="hidden" name="username" value="$user">
                    <input type="text" name="memory" value="$mem_mb" class="rm-mem-input">MB
                    <button type="submit" class="btn btn-default btn-sm">Set</button>
                </form>
            };
        }

        print qq{<tr class="${shade}${suspended_class}">};
        print qq{<td><b>$user</b></td>};
        print qq{<td>$acct->{domain}</td>};
        print qq{<td style="text-align:center">$acct->{plan}</td>};
        print qq{<td style="text-align:center">$status_badge</td>};
        print qq{<td style="text-align:center">@{[$is_managed ? "${mem_mb}MB" : '-']}</td>};
        print qq{<td>$socket_col</td>};
        print qq{<td style="text-align:center">$actions_col</td>};
        print qq{</tr>\n};
    }

    print <<HTML;
</tbody>
</table>
</div>

</div>
HTML
}
