package Flow;

use Carp qw/confess/;
use Data::Dumper;
use File::Slurp qw/read_file write_file/;
use File::Temp qw/tempdir/;
use JSON;
use MIME::Base64;
use POSIX qw/WIFEXITED WEXITSTATUS/;
use Storable qw/nfreeze thaw/;
use Workflow;

use strict;
use warnings;

sub _encode_scalar {
    my $obj = shift;

    return undef if !defined $obj;
    return "" if $obj eq "";

    return MIME::Base64::encode(nfreeze(\$obj));
}

sub _decode_scalar {
    my $str = shift;
    return undef if !defined $str;
    return "" if $str eq "";
    return ${thaw(MIME::Base64::decode($str))};
}

sub _encode_array {
    my $arrayref = shift;
    my @encoded = map {encode($_)} @$arrayref;
    return \@encoded;
}

sub _decode_array {
    my $arrayref = shift;
    my @decoded = map {decode($_)} @$arrayref;
    return \@decoded;
}

sub _encode_hash {
    my $hashref = shift;
    my %encoded = map {encode($_) => encode($hashref->{$_})} keys %$hashref;
    return \%encoded;
}

sub _decode_hash {
    my $hashref = shift;
    my %decoded = map {decode($_) => decode($hashref->{$_})} keys %$hashref;
    return \%decoded;
}

sub encode {
    my $obj = shift;
    if (ref($obj) eq "ARRAY") {
        $obj = _encode_array($obj);
    } elsif (ref($obj) eq "HASH") {
        $obj = _encode_hash($obj);
    } else {
        $obj = _encode_scalar($obj);
    }
    return $obj;
}

sub decode {
    my $obj = shift;
    if (ref($obj) eq "ARRAY") {
        return _decode_array($obj);
    } elsif (ref($obj) eq "HASH") {
        $obj = _decode_hash($obj);
    } else {
        return _decode_scalar($obj);
    }
}

sub encode_io_hash {
    my $io = shift;
    return {
        map {
            my $val = $io->{$_};
            $_ => Flow::encode($val)
        } keys %$io
    };

}

sub decode_io_hash {
    my $io = shift;
    return {
        map {
            my $val = $io->{$_};
            $_ => Flow::decode($val)
        } keys %$io
    };
}


sub run_workflow {
    my ($wf_path, $inp_path, $out_path, $res_path, $plan_id) = setup(@_);

    my $cmd = "flow execute-workflow --xml $wf_path " .
        "--inputs-file $inp_path --outputs-file $out_path " .
        "--resource-file $res_path --plan-id $plan_id --block";

    return run($cmd, $out_path);
}


sub run_workflow_lsf {
    my ($wf_path, $inp_path, $out_path, $res_path, $plan_id) = setup(@_);

    my $cmd = "flow submit-workflow --xml $wf_path " .
        "--inputs-file $inp_path --outputs-file $out_path " .
        "--resource-file $res_path --plan-id $plan_id --block";

    return run($cmd, $out_path);
}


sub setup {
    my ($wf_string, $inputs, $resource_reqs, $plan_id) = @_;
    my $result;

    my $cleanup = !exists $ENV{FLOW_WORKFLOW_NO_CLEANUP};
    my $tmpdir = tempdir(CLEANUP => $cleanup);

    my ($wf_path, $inp_path, $out_path, $res_path) =
            map {join("/", $tmpdir, $_)}
            qw/workflow.xml inputs.json outputs.json resource.json/;

    my $js = new JSON->allow_nonref;

    write_file($wf_path, $wf_string);
    write_file($inp_path, $js->encode(encode_io_hash($inputs)));
    write_file($res_path, $js->encode($resource_reqs));

    return ($wf_path, $inp_path, $out_path, $res_path, $plan_id);
}

sub run {
    my ($cmd, $out_path) = @_;

    print "EXEC: $cmd\n";

    my $ret = system($cmd);
    if (!WIFEXITED($ret) || WEXITSTATUS($ret)) {
        print "Workflow submission failed... returning undef.\n";
        return;
    }

    if (-s $out_path) {
        print "Run_workflow got some outputs... returning them.\n";
        return read_outputs($out_path);
    }
    else {
        print "Run_workflow got no outputs... returning 1.\n";
        return 1;
    }
}


# a convenient way to write out files which are suitable as --inputs-file for
# the workflow-wrapper
sub write_outputs {
    my ($outputs_path, $outputs_hash) = @_;

    my $json = new JSON->allow_nonref;
    my $encoded_content = $json->encode(encode_io_hash($outputs_hash))
        || die "Failed to json encode outputs hash";
    return write_file($outputs_path, $encoded_content)
        || die "Failed to write outputs file";
}

sub read_outputs {
    my $outputs_path = shift;

    my $outputs_str = read_file($outputs_path)
        || die "Failed to slurp file $outputs_path";
    my $json = new JSON->allow_nonref;
    my $outputs = $json->decode($outputs_str)
        || die "Failed to json decode $outputs_str";

    return decode_io_hash($outputs);
}

1;
