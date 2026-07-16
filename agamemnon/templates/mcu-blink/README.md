# MCU blink

This project builds a freestanding SRAM image. Run it without touching flash:

```text
agamemnon build
agamemnon run --transport dap
```

The default board fabric guarantees LED1. Other GPIO routes depend on the
active fabric image.
