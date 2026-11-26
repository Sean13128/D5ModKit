// Apply a reviewed address/name/comment TSV without replacing existing analyst names or comments.
// Args: <plan.tsv> <expected executable sha256> <audit directory>. Run without -readOnly after backup.
//@category D5ModKit.Research

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.SourceType;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class ApplyAiAnnotations extends GhidraScript {
    private String encoded(String value) {
        return Base64.getEncoder().encodeToString((value == null ? "" : value).getBytes(StandardCharsets.UTF_8));
    }
    private void inventory(Path path) throws Exception {
        StringBuilder out = new StringBuilder("address\tname\tsource\tcomment_base64\trepeatable_base64\tbody_bytes\n");
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            out.append(f.getEntryPoint()).append('\t').append(f.getName()).append('\t')
                .append(f.getSymbol().getSource()).append('\t').append(encoded(f.getComment())).append('\t')
                .append(encoded(f.getRepeatableComment())).append('\t').append(f.getBody().getNumAddresses()).append('\n');
        }
        Files.writeString(path, out, StandardCharsets.UTF_8);
    }
    @Override public void run() throws Exception {
        String[] a = getScriptArgs();
        if (a.length != 3) throw new IllegalArgumentException("plan, executable SHA256, audit directory required");
        String actual = currentProgram.getExecutableSHA256();
        if (actual == null || !actual.equalsIgnoreCase(a[1]))
            throw new IllegalStateException("Program executable SHA256 differs: " + actual);
        Path audit = Paths.get(a[2]);
        if (Files.exists(audit)) throw new IllegalStateException("Audit output exists; refuse replacement");
        List<String[]> plan = new ArrayList<>();
        Set<String> addresses = new HashSet<>();
        for (String line : Files.readAllLines(Paths.get(a[0]), StandardCharsets.UTF_8)) {
            if (line.startsWith("address\t") || line.isBlank()) continue;
            String[] row = line.split("\t", -1);
            if (row.length != 3 || !row[1].matches("ai_[A-Za-z0-9_]+") || !row[2].startsWith("[ai] ")
                    || !addresses.add(row[0]) || toAddr(row[0]) == null)
                throw new IllegalArgumentException("Malformed or duplicate AI plan row");
            plan.add(row);
        }
        Files.createDirectories(audit);
        Files.writeString(audit.resolve("program-sha256.txt"), actual + "\n");
        inventory(audit.resolve("functions-before.tsv"));
        StringBuilder result = new StringBuilder("address\tprior_name\tfinal_name\taction\n");
        for (String[] row : plan) {
            var address = toAddr(row[0]);
            Function f = currentProgram.getFunctionManager().getFunctionAt(address);
            String comment = row[2].replace("\\n", "\n");
            if (f != null) {
                String oldName = f.getName();
                boolean rename = f.getSymbol().getSource() == SourceType.DEFAULT && oldName.startsWith("FUN_");
                if (rename) f.setName(row[1], SourceType.USER_DEFINED);
                String oldComment = f.getComment();
                if (oldComment == null || !oldComment.contains(comment))
                    f.setComment((oldComment == null || oldComment.isEmpty() ? "" : oldComment + "\n") + comment);
                result.append(address).append('\t').append(oldName).append('\t').append(f.getName())
                    .append('\t').append(rename ? "renamed-and-commented" : "name-preserved-commented").append('\n');
            } else {
                // Do not create/recover functions or alter disassembly just to improve coverage.
                if (currentProgram.getListing().getInstructionAt(address) == null) {
                    result.append(address).append("\t\t\tskipped-no-instruction\n");
                    continue;
                }
                String prior = currentProgram.getListing().getComment(CodeUnit.PLATE_COMMENT, address);
                currentProgram.getListing().setComment(address, CodeUnit.PLATE_COMMENT,
                    (prior == null || prior.isEmpty() ? "" : prior + "\n") + comment);
                createLabel(address, row[1], false, SourceType.USER_DEFINED);
                result.append(address).append("\t\t").append(row[1]).append("\taddress-only-no-function-created\n");
            }
        }
        inventory(audit.resolve("functions-after.tsv"));
        Files.writeString(audit.resolve("applied.tsv"), result, StandardCharsets.UTF_8);
        println("AI annotations: " + plan.size() + " reviewed entries; existing names preserved");
    }
}
