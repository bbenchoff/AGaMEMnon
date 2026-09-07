# BRAM placement-intent preservation and packer safety

Two independent defects are repaired on the work branch:

- Inferred memory `BEL` attributes could disappear during library mapping.
  The synthesis flow now maps each explicitly constrained memory separately,
  identifies newly created library cells by selection difference, and transfers
  the constraint only when exactly one physical block is produced. It reads
  valid sites from the packaged device table. Invalid sites and single-BEL
  memories requiring multiple blocks fail explicitly. Unconstrained memories
  retain ordinary mapping behavior; generated cell naming is not assumed.
- The optional site-read output helper queried an unassigned BRAM's location
  even when the profile was inactive. Inactive handling is now skipped, and an
  active profile requires a resolved BRAM BEL. Imported BEL names are checked
  against actual resources before location/pin queries, avoiding an assertion
  on unknown names and rejecting a non-BRAM resource.

No graph, selector codeword, BRAM functional configuration, timing model, or
initialized-read admission fence is changed.

## Verification

The three-cell compiled reduction contains only a BRAM output, one slice sink,
and a clock source. Before repair, four tests fail and eight controls pass;
after repair, all twelve pass. These isolate BEL handling and do not qualify
the optional exact site-path tables on an incompatible device graph.

Full synthesis regressions cover four requested sites, multiple constrained
memories, a constrained/unconstrained mixture, an unconstrained control,
bracketed identifiers, invalid sites, and multi-block refusal. The initial
ten-test set had nine failures and one passing unconstrained control on the
old flow. All eleven current cases pass. The broader compiled endpoint,
carry, soft-ripple, BRAM, and synthesis run finishes **205 passed, zero skipped,
zero failures**, 192.43 seconds.

Fresh one-bit and wider-source ROM builds now complete placement and routing
on the unchanged strict graph. The normal default-clock builds then stop at
the existing initialized-read correctness fence. An explicit frequency request
still fails when no interior timing path is modeled. Neither outcome is a
working BRAM image or a timing-closure claim. These safety checks remain intact.

The earlier full-suite result (2,176 passed, 384 skipped) belongs to clean
`4c528c8`, before these BRAM repairs; it is not attributed to this change.

Native source SHA-256:
`1984bb5c85988693a621ad461d95278b171aeef5769087f654b18d91d7ee8858`.
Native executable SHA-256:
`81153a7d1c7487a47463414108072a49e8e4f986014223d7c1881179505b41e7`.

Public main is not promoted by this work-branch change.
