#!/usr/bin/env python3
"""Apply the cluster's AVRCP cover-art patches to a BlueZ 5.87 source tree.

Why: per AVRCP 1.6.2 a target only returns the cover-art handle (attribute
0x08) when it is *specifically* requested — an all-attributes request
(NumAttributes = 0, which is what stock BlueZ sends) must not include it, and
iPhones correctly omit it. So stock BlueZ never sees an ImgHandle. Two
request builders must list every attribute explicitly:

  * ``avrcp_get_element_attributes`` — the control-channel now-playing query;
  * ``avrcp_get_item_attributes``   — the browsing-channel query, which is the
    one actually used on track change for browsing-capable players (iPhone).

Verified working against an iPhone on the car, 2026-08-06.

Usage:  python3 patch_bluez_cover_art.py /path/to/bluez-5.87
Idempotent: re-running on a patched tree is a no-op.
"""

import sys

AVRCP = "/profiles/audio/avrcp.c"

MARKER = "Request every attribute explicitly"

ELEMENT_OLD = """	memset(buf, 0, sizeof(buf));

	set_company_id(pdu->company_id, IEEEID_BTSIG);
	pdu->pdu_id = AVRCP_GET_ELEMENT_ATTRIBUTES;
	pdu->params_len = cpu_to_be16(9);
	pdu->packet_type = AVRCP_PACKET_TYPE_SINGLE;"""

ELEMENT_NEW = """	int i;

	memset(buf, 0, sizeof(buf));

	set_company_id(pdu->company_id, IEEEID_BTSIG);
	pdu->pdu_id = AVRCP_GET_ELEMENT_ATTRIBUTES;
	/* Request every attribute explicitly: per AVRCP 1.6.2 the cover-art
	 * handle (0x08) is only returned when specifically requested, never
	 * as part of an all-attributes (count 0) request. */
	pdu->params[8] = AVRCP_MEDIA_ATTRIBUTE_LAST;
	for (i = 1; i <= AVRCP_MEDIA_ATTRIBUTE_LAST; i++)
		put_be32(i, &pdu->params[9 + (i - 1) * 4]);
	pdu->params_len = cpu_to_be16(9 + AVRCP_MEDIA_ATTRIBUTE_LAST * 4);
	pdu->packet_type = AVRCP_PACKET_TYPE_SINGLE;"""

ELEMENT_BUF_OLD = "uint8_t buf[AVRCP_HEADER_LENGTH + 9];"
ELEMENT_BUF_NEW = \
    "uint8_t buf[AVRCP_HEADER_LENGTH + 9 + AVRCP_MEDIA_ATTRIBUTE_LAST * 4];"

ITEM_OLD = """	struct avrcp_player *player = session->controller->player;
	uint8_t buf[AVRCP_BROWSING_HEADER_LENGTH + 12];
	struct avrcp_browsing_header *pdu = (void *) buf;

	memset(buf, 0, sizeof(buf));

	pdu->pdu_id = AVRCP_GET_ITEM_ATTRIBUTES;
	pdu->params[0] = 0x03;
	put_be64(uid, &pdu->params[1]);
	put_be16(player->uid_counter, &pdu->params[9]);
	pdu->param_len = cpu_to_be16(12);"""

ITEM_NEW = """	struct avrcp_player *player = session->controller->player;
	uint8_t buf[AVRCP_BROWSING_HEADER_LENGTH + 12 +
					AVRCP_MEDIA_ATTRIBUTE_LAST * 4];
	struct avrcp_browsing_header *pdu = (void *) buf;
	int i;

	memset(buf, 0, sizeof(buf));

	pdu->pdu_id = AVRCP_GET_ITEM_ATTRIBUTES;
	pdu->params[0] = 0x03;
	put_be64(uid, &pdu->params[1]);
	put_be16(player->uid_counter, &pdu->params[9]);
	/* Request every attribute explicitly: per AVRCP 1.6.2 the cover-art
	 * handle (0x08) is only returned when specifically requested, never
	 * as part of an all-attributes (count 0) request. */
	pdu->params[11] = AVRCP_MEDIA_ATTRIBUTE_LAST;
	for (i = 1; i <= AVRCP_MEDIA_ATTRIBUTE_LAST; i++)
		put_be32(i, &pdu->params[12 + (i - 1) * 4]);
	pdu->param_len = cpu_to_be16(12 + AVRCP_MEDIA_ATTRIBUTE_LAST * 4);"""


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = sys.argv[1].rstrip("/") + AVRCP
    src = open(path).read()

    if MARKER in src:
        print("already patched — nothing to do")
        return

    # element attributes (control channel): patch inside the function only
    fn = src.find("static void avrcp_get_element_attributes"
                  "(struct avrcp *session)")
    assert fn > 0, "avrcp_get_element_attributes not found"
    seg = src[fn:fn + 1200]
    assert ELEMENT_OLD in seg and ELEMENT_BUF_OLD in seg, \
        "element-attributes pattern drifted — check BlueZ version"
    seg = seg.replace(ELEMENT_BUF_OLD, ELEMENT_BUF_NEW, 1) \
             .replace(ELEMENT_OLD, ELEMENT_NEW, 1)
    src = src[:fn] + seg + src[fn + 1200:]

    # item attributes (browsing channel — the track-change path on iPhones)
    assert ITEM_OLD in src, \
        "item-attributes pattern drifted — check BlueZ version"
    src = src.replace(ITEM_OLD, ITEM_NEW, 1)

    open(path, "w").write(src)
    print("patched", path)


if __name__ == "__main__":
    main()
