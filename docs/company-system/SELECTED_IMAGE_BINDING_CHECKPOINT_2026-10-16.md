# Selected image binding checkpoint — 2026-10-16

The selected template now accepts the exact nominated amd64 manifest-reference/
configuration-ID pair and rejects unknown, aliased, equalized or cross-paired
values. Public fields and every other template/native guard remain unchanged.
The coherent1,620-file backend passes **4,247 unit tests** with19 existing warnings
in73.12s; the four-file component passes129 focused tests, configured strict typing
and Ruff check/format. Independent source review is favorable.

The original finite repro passes both lower policy/runtime models and an equalized
control, then fails the legitimate distinct pair at the old template equality
check. Two meaningful new reds reproduce that rejection and acceptance of an
unknown equalized pair before the fix. Their original sources/logs are preserved.

The new pure guard checks the exact architecture, full immutable local reference,
manifest c4d552… and image/config ID8f3dff…. The retained manifest/load/preflight
records establish that correspondence. This is a configuration description;
it does not observe, load or authorize an image. Unknown ARM64 images remain
unsupported until their own reviewed correspondence and runtime qualification.
Selected fixtures use this image pair while retaining supplied synthetic artifacts.
Historical raw golden wires and native capability/image/policy checks are unchanged.

| Evidence | SHA256 |
| --- | --- |
| Original primary-validator repro receipt | `01349a214c7875f4e3542320a9ef5ea4de69c4f3d732a7bc0e3299f3c08628b0` |
| Four-file held component | `df43f65d9f1638be048c9618258bd0a0a2554ec23ac563ab9fa8e990f725c2cc` |
| Author focus/static receipt | `20ce5b89654764ff3afaf30ede73edca3334bf47ae196811efdfc95d2d1c0c36` |
| Independent source review | `de4cd61440e83928519e905a4a4bdc3841dc6865fbf05f43bfabb47956cbbb5a` |
| Root coherent check receipt | `251a50f835b733304142df3cb455252801c2660f03a2ffb4c06dd067e6ebf573` |

The [actual full517 preparation](FULL_CAS_PREPARATION_CHECKPOINT_2026-10-16.md)
remains separately qualified. Read-only reuse and fresh real Node-v4 runtime/CAS/
policy/candidate/ordered E-EV template pins must precede new Strategy inception.
Current complete V8 stays disabled pending genuine opaque Company execution and
independent acceptance. This fix supplies no READ scope, approval, lease or permit.
