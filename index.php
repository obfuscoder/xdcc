<?php
    if ($_GET['qnet'] != "") {
        $add = fopen("downloads/add/" . uniqid(), "w");
        fwrite($add, $_GET['qnet'] . "\t" . $_GET['qnick'] . "\t" . $_GET['qnum'] . "\t" . $_GET['qname'] . "\n");
        fclose($add);
        header('Location: '.$_SERVER['PHP_SELF'].'?s='.$_GET['s']);
        die();
    }
?>
<h3>QUEUE</h3>
<pre>
<?php
	echo file_get_contents('downloads/queue.txt');
?>
</pre>
<h3>DONE</h3>
<pre>
<?php
	echo file_get_contents('downloads/done.txt');
?>
</pre>
<h3>FAILED</h3>
<pre>
<?php
	echo file_get_contents('downloads/failed.txt');
?>
</pre>
<h3>Search</h3>
<form>
    <input name="s" value="<?php echo $_GET["s"] ?>">
</form>
<?php if ($_GET["s"] != ""): ?>
<table>
    <tr>
        <th>Network</th>
        <th>Channel</th>
        <th>Nick</th>
        <th>Number</th>
        <th>Filename</th>
        <th>Size</th>
        <th>Gets</th>
        <th>Date</th>
    </tr>
<?php
    $db = new SQLite3('downloads/xdcc.db');
    $parts = explode(" ", $_GET["s"]);

    function name_like($s) { return "name like '%$s%'"; }

    $where = join(" and ", array_map("name_like", $parts));

    $results = $db->query("SELECT * FROM offers where $where");
    while ($row = $results->fetchArray()):
        $query_params = array(
            's' => $_GET["s"],
            'qnet' => $row["network"],
            'qnick' => $row["nick"],
            'qnum' => $row["number"],
            'qname' => $row["name"]
        );
        ?>
    <tr>
        <td><?php echo $row["network"] ?></td>
        <td><?php echo $row["channel"] ?></td>
        <td><?php echo $row["nick"] ?></td>
        <td><?php echo $row["number"] ?></td>
        <td><a href="?<?php echo http_build_query($query_params) ?>"><?php echo $row["name"] ?></a></td>
        <td><?php echo $row["size"] ?></td>
        <td><?php echo $row["gets"] ?></td>
        <td><?php echo $row["date"] ?></td>
    </tr>
    <?php endwhile; ?>
</table>
<?php endif ?>
